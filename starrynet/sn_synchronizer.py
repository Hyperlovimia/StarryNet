#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""
StarryNet: empowering researchers to evaluate futuristic integrated space and terrestrial networks.
author: Zeqi Lai (zeqilai@tsinghua.edu.cn) and Yangtao Deng (dengyt21@mails.tsinghua.edu.cn)
"""
import time
import threading
import math
import os
import glob
import random
import ipaddress
import heapq
from enum import Enum
from collections import defaultdict
from typing import List, Tuple, Dict, Any
from dataclasses import dataclass, field
from .sn_observer import *
from .sn_utils import *
from .sn_daemon_client import SSHDaemonClient

EXTRA_LINK_DELAY = 1  # ms, for extra nodes connected to GS

class NodeType(Enum):
    SAT = 1
    GS = 2
    EXTRA = 3

@dataclass
class LinkInfo:
    dst: str
    addr4: ipaddress.IPv4Interface
    addr6: ipaddress.IPv6Interface
    if_id: int = None

@dataclass
class NodeInfo:
    name: str
    node_type: NodeType = NodeType.SAT
    cbf_t: List[Tuple[float, float, float]] = field(default_factory=list)
    lla_t: List[Tuple[float, float, float]] = field(default_factory=list)
    links_t: List[Dict[str, LinkInfo]] = field(default_factory=list)
    ifidx_next: int = 100
    addr4: ipaddress.IPv4Address = None
    addr6: ipaddress.IPv6Address = None
    worker: SSHDaemonClient = None

@dataclass
class EventRecord:
    event_id: str
    time: int
    event_type: str
    params: Dict[str, Any] = field(default_factory=dict)
    result_mode: str = 'none'
    status: str = 'queuing'
    created_at: float = field(default_factory=time.time)
    triggered_at: float = None
    finished_at: float = None
    result: Any = None
    error: str = None
    task_refs: List[Dict[str, Any]] = field(default_factory=list)

    def __lt__(self, other):
        return (self.time, self.created_at, self.event_id) < (
            other.time, other.created_at, other.event_id
        )

class StarryNet():

    def __init__(self, configuration_file_path, GS_lat_long, GS_links = None,
                 extra_nodes_links = None, run_id: str = "default",
                 artifact_root: str = None):
        # Initialize constellation information.
        sn_args = sn_load_file(configuration_file_path)
        self.run_id = run_id
        self.shell_lst = sn_args.shell_lst
        self.gs_lat_long = GS_lat_long
        self.link_style = sn_args.link_style
        self.link_policy = sn_args.link_policy
        self.IP_version = sn_args.IP_version
        self.step = sn_args.step
        self.duration = sn_args.duration
        self.sat_bandwidth = sn_args.sat_bandwidth
        self.sat_ground_bandwidth = sn_args.sat_ground_bandwidth
        self.sat_loss = sn_args.sat_loss
        self.sat_ground_loss = sn_args.sat_ground_loss
        self.antenna_number = sn_args.antenna_number
        self.elevation = sn_args.antenna_elevation
        self.configuration_dir = os.path.dirname(
            os.path.abspath(configuration_file_path))
        self.experiment_name = sn_args.cons_name\
            +'-'+ sn_args.link_style +'-'+ sn_args.link_policy
        self.gs_dirname = 'GS'
        for shell_id, shell in enumerate(self.shell_lst):
            shell['name'] = f"shell{shell_id}"

        base_artifact_root = artifact_root or os.path.join(
            self.configuration_dir, self.experiment_name
        )
        self.local_dir = os.path.join(base_artifact_root, self.run_id)
        self._init_local()
        
        # Initialize Observer for topology computation
        self.observer = Observer(configuration_file_path, GS_lat_long, 
                            self.antenna_number, self.elevation)
        
        # Compute topology and get updates
        sat_t_shell, gs_t = self.observer.compute_topology(GS_links)
        self.nodes, self.changes_t = self._process_topo(sat_t_shell, gs_t, extra_nodes_links)

        self._assign_worker([shell[0] for shell in sat_t_shell], sn_args.machine_lst)

        self.events: List[EventRecord] = []
        self.event_history: Dict[str, EventRecord] = {}
        self._event_seq = 0
        self._event_lock = threading.Lock()
        self._stop_event = threading.Event()

    def _init_local(self):
        for txt_file in glob.glob(os.path.join(self.local_dir, '*.txt')):
            os.remove(txt_file)
        for shell in self.shell_lst:
            os.makedirs(os.path.join(self.local_dir, shell['name']), exist_ok=True)
        os.makedirs(os.path.join(self.local_dir, self.gs_dirname), exist_ok=True)

    def _process_topo(self, sat_t_shell, gs_t, extra_nodes_links):
        gs_name_lst, gs_cbf, gsls_t = gs_t
        nodes = {}
        idx_dict = {}
        cnt = 0
        changes_t = [{'add': [], 'update':[], 'del': []} for _ in range(len(gsls_t))]

        for name_lst, sat_cbf_t, sat_lla_t, isls_t in sat_t_shell:
            for sat_name in name_lst:
                nodes[sat_name] = NodeInfo(name=sat_name, node_type=NodeType.SAT, cbf_t=[], links_t=[{} for _ in range(len(isls_t))])
        for name_lst, sat_cbf_t, sat_lla_t, isls_t in sat_t_shell:
            old_states = {sat_name: {} for sat_name in name_lst}
            for t, (cbf_lst, lla_lst, isls_lst) in enumerate(zip(sat_cbf_t, sat_lla_t, isls_t)):
                for sat_name, cbf, lla, isls in zip(name_lst, cbf_lst, lla_lst, isls_lst):
                    nodes[sat_name].cbf_t.append((cbf[0], cbf[1], cbf[2]))
                    nodes[sat_name].lla_t.append((lla[0], lla[1], lla[2]))
                    new_state = {}
                    for isl in isls:
                        dst = isl[0]
                        new_state[dst] = isl[1]
                        key = (sat_name, dst)
                        if key in idx_dict:
                            idx = idx_dict[key]
                        else:
                            idx = cnt
                            idx_dict[key] = idx
                            cnt += 1
                        nodes[sat_name].links_t[t][dst] = LinkInfo(
                            dst=dst,
                            addr4=ipaddress.IPv4Interface(f'10.{idx >> 8}.{idx & 0xFF}.10/24'),
                            addr6=ipaddress.IPv6Interface(f'2000:{idx >> 8}:{idx & 0xFF}::10/48')
                        )
                        nodes[dst].links_t[t][sat_name] = LinkInfo(
                            dst=sat_name,
                            addr4=ipaddress.IPv4Interface(f'10.{idx >> 8}.{idx & 0xFF}.40/24'),
                            addr6=ipaddress.IPv6Interface(f'2000:{idx >> 8}:{idx & 0xFF}::40/48')
                        )
                    old_state = old_states[sat_name]
                    for dst, old_delay in old_state.items():
                        if dst not in new_state:
                            changes_t[t]['del'].append((sat_name, dst))
                        elif abs(old_delay - new_state[dst]) > 1e-2:
                            changes_t[t]['update'].append((sat_name, dst, f'{new_state[dst]:.2f}'))
                        else:
                            # not accumlate
                            new_state[dst] = old_delay
                    for dst, delay in new_state.items():
                        if dst not in old_state:
                            src_node = nodes[sat_name]
                            src_link = src_node.links_t[t][dst]
                            src_link.if_id = src_node.ifidx_next
                            src_node.ifidx_next += 1
                            dst_node = nodes[dst]
                            dst_link = dst_node.links_t[t][sat_name]
                            dst_link.if_id = dst_node.ifidx_next
                            dst_node.ifidx_next += 1
                            changes_t[t]['add'].append((
                                sat_name, dst, f'{delay:.2f}',
                                src_link.if_id, src_link.addr4.compressed, src_link.addr6.compressed,
                                dst_link.if_id, dst_link.addr4.compressed, dst_link.addr6.compressed,
                            ))
                    old_states[sat_name] = new_state
        
        old_state = {}
        gs_lla = self.gs_lat_long
        for gs_index, gs_name in enumerate(gs_name_lst):
            nodes[gs_name] = NodeInfo(name=gs_name, node_type=NodeType.GS, cbf_t=[], links_t=[])
            if gs_index < len(gs_lla):
                lat_lon = gs_lla[gs_index]
                altitude = lat_lon[2] if len(lat_lon) > 2 else 0
                nodes[gs_name].lla_t = [(lat_lon[0], lat_lon[1], altitude) for _ in range(len(gsls_t))]
            old_states[gs_name] = {}
        for t, gsls_lst in enumerate(gsls_t):
            for gs_name, cbf, gsls in zip(gs_name_lst, gs_cbf, gsls_lst):
                nodes[gs_name].cbf_t.append((cbf[0], cbf[1], cbf[2]))
                links = {}
                new_state = {}
                for gsl in gsls:
                    sat = gsl[0]
                    new_state[sat] = gsl[1]
                    key = (gs_name, sat)
                    if key in idx_dict:
                        idx = idx_dict[key]
                    else:
                        idx = cnt
                        idx_dict[key] = idx
                        cnt += 1
                    links[sat] = LinkInfo(
                        dst=sat,
                        addr4=ipaddress.IPv4Interface(f'11.{idx >> 8}.{idx & 0xFF}.40/24'),
                        addr6=ipaddress.IPv6Interface(f'2001:{idx >> 8}:{idx & 0xFF}::40/48')
                    )
                    nodes[sat].links_t[t][gs_name] = LinkInfo(
                        dst=gs_name,
                        addr4=ipaddress.IPv4Interface(f'11.{idx >> 8}.{idx & 0xFF}.10/24'),
                        addr6=ipaddress.IPv6Interface(f'2001:{idx >> 8}:{idx & 0xFF}::10/48')
                    )
                nodes[gs_name].links_t.append(links)

                old_state = old_states[gs_name]
                for dst, old_delay in old_state.items():
                    if dst not in new_state:
                        changes_t[t]['del'].append((gs_name, dst))
                    elif abs(old_delay - new_state[dst]) > 1e-2:
                        changes_t[t]['update'].append((gs_name, dst, f'{new_state[dst]:.2f}'))
                    else:
                        # not accumlate
                        new_state[dst] = old_delay
                for dst, delay in new_state.items():
                    if dst not in old_state:
                        src_node = nodes[gs_name]
                        src_link = links[dst]
                        src_link.if_id = src_node.ifidx_next
                        src_node.ifidx_next += 1
                        dst_node = nodes[dst]
                        dst_link = dst_node.links_t[t][gs_name]
                        dst_link.if_id = dst_node.ifidx_next
                        dst_node.ifidx_next += 1
                        changes_t[t]['add'].append((
                            gs_name, dst, f'{delay:.2f}',
                            src_link.if_id, src_link.addr4.compressed, src_link.addr6.compressed,
                            dst_link.if_id, dst_link.addr4.compressed, dst_link.addr6.compressed,
                        ))
                old_states[gs_name] = new_state
        if extra_nodes_links:
            for name, links in extra_nodes_links.items():
                extra_node = NodeInfo(name=name, node_type=NodeType.EXTRA, cbf_t=[], links_t=[{} for _ in range(len(gsls_t))])
                anchor_node = None
                for dst in links:
                    dst_node = nodes.get(dst)
                    if dst_node is None:
                        continue    # single directed
                        # raise ValueError(f"Extra node {name} links to non-existent node {dst}")
                    if dst_node.node_type == NodeType.SAT:
                        raise ValueError(f"Extra node {name} cannot link to satellite {dst}")
                    if anchor_node is None:
                        anchor_node = dst_node
                    for t in range(len(dst_node.links_t)):
                        dst_links = dst_node.links_t[t]
                        key = (name, dst)
                        if key in idx_dict:
                            idx = idx_dict[key]
                        else:
                            idx = cnt
                            idx_dict[key] = idx
                            cnt += 1
                        extra_node.links_t[t][dst] = LinkInfo(
                            dst=dst,
                            addr4=ipaddress.IPv4Interface(f'12.{idx >> 8}.{idx & 0xFF}.40/24'),
                            addr6=ipaddress.IPv6Interface(f'2002:{idx >> 8}:{idx & 0xFF}::40/48')
                        )
                        dst_links[name] = LinkInfo(
                            dst=name,
                            addr4=ipaddress.IPv4Interface(f'12.{idx >> 8}.{idx & 0xFF}.10/24'),
                            addr6=ipaddress.IPv6Interface(f'2002:{idx >> 8}:{idx & 0xFF}::10/48')
                        )
                    src_link = extra_node.links_t[0][dst]
                    src_link.if_id = extra_node.ifidx_next
                    extra_node.ifidx_next += 1
                    dst_link = dst_node.links_t[0][name]
                    dst_link.if_id = dst_node.ifidx_next
                    dst_node.ifidx_next += 1
                    changes_t[0]['add'].append((
                        name, dst, f'{EXTRA_LINK_DELAY:.2f}',
                        src_link.if_id, src_link.addr4.compressed, src_link.addr6.compressed,
                        dst_link.if_id, dst_link.addr4.compressed, dst_link.addr6.compressed,
                    ))
                if anchor_node is not None:
                    extra_node.cbf_t = list(anchor_node.cbf_t)
                    extra_node.lla_t = list(anchor_node.lla_t)
                nodes[name] = extra_node
        return nodes, changes_t

    def _assign_worker(self, sat_names_shell, machine_lst):
        assert len(sat_names_shell) == len(self.shell_lst)

        # TODO: better partition
        node_mid_dict = {}
        assigned_shell_lst = []
        if len(sat_names_shell) * 2 <= len(machine_lst):
            # need intra-shell partition
            sat_total = sum(len(sat_names) for sat_names in sat_names_shell)
            sat_per_machine = sat_total // len(machine_lst)
            remainder = sat_total % len(machine_lst)

            shell_id, sat_id = 0, 0
            sat_names = []
            for i, worker in enumerate(machine_lst):
                sat_nr = sat_per_machine
                if i < remainder:
                    sat_nr += 1

                assigned_shells = []
                for _ in range(sat_nr):
                    sat_names.append(sat_names_shell[shell_id][sat_id])
                    node_mid_dict[sat_names[-1]] = i
                    sat_id += 1
                    if(sat_id >= len(sat_names_shell[shell_id])):
                        assigned_shells.append((self.shell_lst[shell_id]['name'], sat_names))
                        shell_id += 1
                        sat_id = 0
                        sat_names = []
                if len(sat_names) > 0:
                    assigned_shells.append((self.shell_lst[shell_id]['name'], sat_names))
                    sat_names = []
                print(assigned_shells)
                assigned_shell_lst.append(assigned_shells)
        else:
            # only divide shell
            shell_per_machine = len(self.shell_lst) // len(machine_lst)
            remainder = len(sat_names_shell) % len(machine_lst)

            shell_id = 0
            for i, worker in enumerate(machine_lst):
                shell_num = shell_per_machine
                if i < remainder:
                    shell_num += 1
                assigned_shells = [
                    (self.shell_lst[j]['name'], sat_names_shell[j])
                      for j in range(shell_id, shell_id + shell_num)
                ]
                # all satellites of a shell assigned to a single machine
                for shell_name, sat_names in assigned_shells:
                    for sat_name in sat_names:
                        node_mid_dict[sat_name] = i
                assigned_shell_lst.append(assigned_shells)
                shell_id += shell_num

        # TODO: better ground station assign
        for name, node in self.nodes.items():
            if name in node_mid_dict:
                continue
            # assigned to the machine of its first neighbor
            for dst in node.links_t[0]:
                dst_mid = node_mid_dict.get(dst)
                if dst_mid is not None:
                    node_mid_dict[name] = dst_mid
                    break
            # TODO: otherwise?
            if name not in node_mid_dict:
                node_mid_dict[name] = 0

        ip_lst = [worker['IP'] for worker in machine_lst]
        assign_obj = {
            'shell_num': len(self.shell_lst),
            'node_mid_dict': node_mid_dict,
            'ip': ip_lst,
        }

        worker_lst = []
        for i, worker in enumerate(machine_lst):
            worker_lst.append(SSHDaemonClient(
                host=worker.get('IP', '127.0.0.1'),
                port=worker.get('port', 18888),
                username=worker.get('username', 'root'),
                password=worker.get('password', ''),
                timeout=30,
                run_id=self.run_id,
            ))
        self.worker_lst: List[SSHDaemonClient] = worker_lst
        self.config_json = assign_obj

    def create_nodes(self):
        print('Initializing nodes ...')
        begin = time.time()
        self.undamaged_lst = list()
        self.total_sat_lst = list()
        for worker in self.worker_lst:
            worker.send_config(
                self.config_json['shell_num'], 
                self.config_json['node_mid_dict'],
                self.config_json['ip']
            )
            node_addrs = worker.init_nodes()
            for name, (addr4, addr6) in node_addrs.items():
                node = self.nodes[name]
                node.addr4 = ipaddress.IPv4Interface(addr4)
                node.addr6 = ipaddress.IPv6Interface(addr6)
                node.worker = worker
                if node.node_type == NodeType.SAT:
                    self.undamaged_lst.append(name)
                    self.total_sat_lst.append(name)
        print("Node initialization:", time.time() - begin, "s consumed.")

    def create_links(self):
        print('Initializing links using pre-computed topology data...')
        thread_lst = []
        begin = time.time()
        
        # Get initial topology data from Observer (t=1 corresponds to initial state)
        initial_network_update = self.changes_t[0]

        initial_network_update['isl_bw'] = str(self.sat_bandwidth)
        initial_network_update['isl_loss'] = str(self.sat_loss)
        initial_network_update['gsl_bw'] = str(self.sat_ground_bandwidth)
        initial_network_update['gsl_loss'] = str(self.sat_ground_loss)
        
        for worker in self.worker_lst:
            thread = threading.Thread(
                target=worker.update_network,
                args=(initial_network_update,)
            )
            thread.start()
            thread_lst.append(thread)
        
        for thread in thread_lst:
            thread.join()
        
        print("Link initialization:", time.time() - begin, 's consumed.')

    def run_routing_daemon(self, bird_conf_path, node_lst='all'):
        with open(bird_conf_path, 'r') as f:
            bird_conf = f.read()
        print('Initializing routing ...')
        if node_lst == 'all':
            for worker in self.worker_lst:
                worker.init_routing('all', bird_conf)
            print("Routing daemon initialized. Wait 30s for route converged")
        else:
            rtd_lsts = defaultdict(list)
            for name, node in self.nodes.items():
                rtd_lsts[node.worker].append(name)
            for worker, names in rtd_lsts.items():
                worker.init_routing(','.join(names), bird_conf)

        for i in range(30):
            if self._stop_event.is_set():
                break
            print(f'\r{i} / 30', end=' ')
            time.sleep(1)
        print("Routing started!")

    def request_stop(self):
        self._stop_event.set()

    def _worker_for_node(self, node):
        node_info = self.nodes.get(node)
        if node_info is None:
            return None
        return node_info.worker

    def _next_event_id(self):
        self._event_seq += 1
        return f"e{self._event_seq}"

    def _event_to_dict(self, event: EventRecord):
        result = {
            "event_id": event.event_id,
            "time": event.time,
            "type": event.event_type,
            "params": event.params,
            "result_mode": event.result_mode,
            "status": event.status,
            "created_at": event.created_at,
            "triggered_at": event.triggered_at,
            "finished_at": event.finished_at,
            "error": event.error,
            "task_refs": event.task_refs,
        }
        if event.result is not None:
            result["result"] = event.result
        return result

    def _queue_event(self, event_type, t, params=None, result_mode='none'):
        with self._event_lock:
            event = EventRecord(
                event_id=self._next_event_id(),
                time=self._validate_t(t),
                event_type=event_type,
                params=params or {},
                result_mode=result_mode,
            )
            heapq.heappush(self.events, event)
            self.event_history[event.event_id] = event
        return event.event_id

    def _set_event_result(self, event: EventRecord, result=None, error=None, task_refs=None):
        event.finished_at = time.time()
        event.result = result
        event.error = error
        if task_refs is not None:
            event.task_refs = task_refs
        event.status = 'failed' if error else 'succeeded'
        return event

    def list_events(self):
        with self._event_lock:
            events = list(self.event_history.values())
        events.sort(key=lambda item: (item.time, item.created_at, item.event_id))
        return [self._event_to_dict(event) for event in events]

    def get_event(self, event_id):
        with self._event_lock:
            event = self.event_history.get(event_id)
        if event is None:
            return {}
        return self._event_to_dict(event)

    def list_tasks(self, node=None, status=None, task_type=None):
        if node is not None:
            worker = self._worker_for_node(node)
            if worker is None:
                return []
            return worker.list_tasks(node=node, status=status, task_type=task_type)

        tasks = []
        seen = set()
        for worker in self.worker_lst:
            worker_tasks = worker.list_tasks(status=status, task_type=task_type)
            for task in worker_tasks:
                task_id = task.get('task_id')
                if task_id in seen:
                    continue
                seen.add(task_id)
                tasks.append(task)
        tasks.sort(key=lambda item: item.get('created_at', 0))
        return tasks

    def get_task(self, task_id, node=None):
        if node is not None:
            worker = self._worker_for_node(node)
            if worker is None:
                return {}
            return worker.get_task(task_id)

        for worker in self.worker_lst:
            result = worker.get_task(task_id)
            if result:
                return result
        return {}

    def get_task_output(self, task_id, node=None):
        if node is not None:
            worker = self._worker_for_node(node)
            if worker is None:
                return {}
            return worker.get_task_output(task_id)

        for worker in self.worker_lst:
            result = worker.get_task_output(task_id)
            if result:
                return result
        return {}

    # static information
    def get_distance(self, node1, node2, t):
        node1, node2 = self.nodes.get(node1), self.nodes.get(node2)
        if node1 is None or node2 is None:
            return None
        
        tid = t // self.step
        xyz1 = node1.cbf_t[tid] if tid < len(node1.cbf_t) else node1.cbf_t[-1]
        xyz2 = node2.cbf_t[tid] if tid < len(node2.cbf_t) else node2.cbf_t[-1]
        dx, dy, dz = xyz1[0] - xyz2[0], xyz1[1] - xyz2[1], xyz1[2] - xyz2[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def get_neighbors(self, node, t):
        node = self.nodes.get(node)
        if node is None:
            return []
        
        tid = t // self.step
        return list(node.links_t[tid].keys())

    def get_GSes(self, node, t):
        node = self.nodes.get(node)
        if node is None:
            return []
        
        tid = t // self.step
        GSes = []
        for dst in node.links_t[tid]:
            dst_node = self.nodes[dst]
            if dst_node.node_type == NodeType.GS:
                GSes.append(dst)
        return GSes

    def get_position(self, node, t):
        node = self.nodes.get(node)
        if node is None:
            return None

        tid = t // self.step
        return node.cbf_t[tid] if tid < len(node.cbf_t) else node.cbf_t[-1]

    def get_lla(self, node, t):
        node = self.nodes.get(node)
        if node is None or not node.lla_t:
            return None

        tid = t // self.step
        return node.lla_t[tid] if tid < len(node.lla_t) else node.lla_t[-1]

    def get_IP(self, node):
        node = self.nodes.get(node)
        if node is None:
            return ()
        return node.addr4.compressed, node.addr6.compressed

    # dynamic events
    def _validate_t(self, t):
        if t >= self.duration:
            t = round(self.duration) - 1
        elif t < 0:
            t = 0
        else:
            t = round(t)
        return t

    def check_utility(self, t):
        return self._queue_event('check_utility', t, result_mode='inline')

    def _run_check_utility_event(self, event: EventRecord):
        results = {}
        for mid, worker in enumerate(self.worker_lst):
            result = worker.check_utility()
            key = f'machine{mid}'
            results[key] = result
        self._set_event_result(event, result=results)

    def check_routing_table(self, node, t):
        return self._queue_event(
            'check_routing_table',
            t,
            params={'node': node},
            result_mode='inline',
        )

    def _run_check_routing_table_event(self, event: EventRecord):
        node = event.params['node']
        result = self.nodes[node].worker.check_routing_table(node)
        self._set_event_result(event, result=result)

    def set_damage(self, damaging_ratio, t):
        return self._queue_event(
            'damage',
            t,
            params={'damaging_ratio': damaging_ratio},
        )

    def _run_damage_event(self, event: EventRecord):
        damaging_ratio = event.params['damaging_ratio']
        damage_lsts = {worker: [] for worker in self.worker_lst}
        cur_num = len(self.undamaged_lst)
        need_damage_num = min(len(self.total_sat_lst) * damaging_ratio, cur_num)
        while cur_num - len(self.undamaged_lst) < need_damage_num and self.undamaged_lst:
            sat = self.undamaged_lst.pop(
                random.randint(0, len(self.undamaged_lst) - 1)
            )
            worker = self.nodes[sat].worker
            damage_lsts[worker].append(sat)
        for worker, lst in damage_lsts.items():
            if lst:
                worker.damage_nodes(lst)
        machine_map = {}
        for mid, worker in enumerate(self.worker_lst):
            if damage_lsts[worker]:
                machine_map[f'machine{mid}'] = damage_lsts[worker]
        self._set_event_result(
            event,
            result={
                'damaged_nodes': sum(len(lst) for lst in damage_lsts.values()),
                'machines': machine_map,
            },
        )

    def set_recovery(self, t):
        return self._queue_event('recovery', t)

    def _run_recovery_event(self, event: EventRecord):
        for worker in self.worker_lst:
            worker.recover_nodes()
        self.undamaged_lst = self.total_sat_lst.copy()
        self._set_event_result(event, result={'recovered': True})

    def set_static_route(self, src, dst, next_hop, t):
        return self._queue_event(
            'static_route',
            t,
            params={'src': src, 'dst': dst, 'next_hop': next_hop},
        )

    def set_netlink(self, node, nlmsg, t):
        return self._queue_event(
            'netlink',
            t,
            params={'node': node, 'nlmsg': nlmsg},
        )

    def set_ping(self, src, dst, t, extra_args=[]):
        return self._queue_event(
            'ping',
            t,
            params={'src': src, 'dst': dst, 'extra_args': list(extra_args)},
            result_mode='task',
        )

    def set_iperf(self, src, dst, t, src_args = [], dst_args = []):
        return self._queue_event(
            'iperf',
            t,
            params={
                'src': src,
                'dst': dst,
                'src_args': list(src_args),
                'dst_args': list(dst_args),
            },
            result_mode='task',
        )

    def exec_at(self, node, cmd, t):
        return self._queue_event(
            'exec',
            t,
            params={'node': node, 'cmd': cmd},
            result_mode='task',
        )

    def _run_batch_events(self, events: List[EventRecord], event_type, builder, sender, task_ref_builder=None):
        worker_args = defaultdict(list)
        worker_events = defaultdict(list)
        for event in events:
            args = builder(event)
            worker = self.nodes[args[0]].worker
            worker_args[worker].append(args)
            worker_events[worker].append(event)

        for worker, args_lst in worker_args.items():
            response = sender(worker, args_lst) or {}
            results = response.get('result', []) if isinstance(response, dict) else []
            if not isinstance(results, list):
                for event in worker_events[worker]:
                    self._set_event_result(event, result=results)
                continue
            for index, event in enumerate(worker_events[worker]):
                if index >= len(results):
                    self._set_event_result(
                        event,
                        error=f'{event_type} returned fewer results than expected',
                    )
                    continue
                result = results[index]
                if result.get('ok', True):
                    task_refs = task_ref_builder(result) if task_ref_builder else None
                    self._set_event_result(event, result=result, task_refs=task_refs)
                else:
                    self._set_event_result(event, error=result.get('error', f'{event_type} failed'), result=result)

    def _pop_due_events(self, real_t):
        due_events = []
        with self._event_lock:
            while self.events and self.events[0].time <= real_t:
                due_events.append(heapq.heappop(self.events))
        return due_events

    def _event(self, real_t):
        due_events = self._pop_due_events(real_t)
        if not due_events:
            return

        grouped = defaultdict(list)
        for event in due_events:
            event.status = 'running'
            event.triggered_at = time.time()
            grouped[event.event_type].append(event)

        for event in grouped.get('damage', []):
            self._run_damage_event(event)
        for event in grouped.get('recovery', []):
            self._run_recovery_event(event)
        for event in grouped.get('check_utility', []):
            self._run_check_utility_event(event)
        for event in grouped.get('check_routing_table', []):
            self._run_check_routing_table_event(event)

        if grouped.get('static_route'):
            self._run_batch_events(
                grouped['static_route'],
                'static_route',
                lambda event: (
                    event.params['src'],
                    event.params['dst'],
                    event.params['next_hop'],
                ),
                lambda worker, args_lst: worker.static_route_batch(args_lst),
            )
        if grouped.get('netlink'):
            self._run_batch_events(
                grouped['netlink'],
                'netlink',
                lambda event: (
                    event.params['node'],
                    event.params['nlmsg'],
                ),
                lambda worker, args_lst: worker.netlink_batch(args_lst),
            )
        if grouped.get('ping'):
            self._run_batch_events(
                grouped['ping'],
                'ping',
                lambda event: (
                    event.params['src'],
                    event.params['dst'],
                    event.params.get('extra_args', []),
                ),
                lambda worker, args_lst: worker.ping_batch(args_lst),
                lambda result: [{'task_id': result['task_id'], 'output_file': result.get('output_file')}],
            )
        if grouped.get('iperf'):
            self._run_batch_events(
                grouped['iperf'],
                'iperf',
                lambda event: (
                    event.params['src'],
                    event.params['dst'],
                    event.params.get('src_args', []),
                    event.params.get('dst_args', []),
                ),
                lambda worker, args_lst: worker.iperf_batch(args_lst),
                lambda result: [
                    {'task_id': result['server_task_id'], 'role': 'server'},
                    {'task_id': result['client_task_id'], 'role': 'client'},
                ],
            )
        if grouped.get('exec'):
            self._run_batch_events(
                grouped['exec'],
                'exec',
                lambda event: (
                    event.params['node'],
                    event.params['cmd'],
                ),
                lambda worker, args_lst: worker.exec_batch(args_lst),
                lambda result: [{'task_id': result['task_id'], 'output_file': result.get('output_file')}],
            )

    def start_emulation(self):
        start_time = time.time()
        print('Tick event at 0 s')
        self._event(0)

        tid = 1
        while tid < len(self.changes_t):
            if self._stop_event.is_set():
                break
            t = tid * self.step
            target_time = start_time + t

            now = time.time()
            if now < target_time:
                sleep_time = target_time - now
                print('Sleeping', sleep_time, 's until', t, 's')
                if self._stop_event.wait(sleep_time):
                    break

            start = time.time()
            print("\nUpdate networks using pre-computed topology...")

            network_change = self.changes_t[tid]
            network_change['isl_bw'] = str(self.sat_bandwidth)
            network_change['isl_loss'] = str(self.sat_loss)
            network_change['gsl_bw'] = str(self.sat_ground_bandwidth)
            network_change['gsl_loss'] = str(self.sat_ground_loss)

            conn_threads = []
            for worker in self.worker_lst:
                thread = threading.Thread(
                    target=worker.update_network,
                    args=(network_change,)
                )
                thread.start()
                conn_threads.append(thread)
            for thread in conn_threads:
                thread.join()
            update_end = time.time()

            print("Trigger events at", t, "s ...")
            self._event(t)
            end = time.time()
            elapsed = end - start
            print(elapsed, "s elapsed,", update_end-start, "s for network update")
            tid += 1

    def clean(self):
        self.request_stop()
        print("Removing containers and links...")
        for worker in self.worker_lst:
            worker.clean()
        print("All containers and links removed.")
