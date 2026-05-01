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
from enum import Enum
from collections import defaultdict
from typing import List, Tuple, Dict, Callable
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
    links_t: List[Dict[str, LinkInfo]] = field(default_factory=list)
    ifidx_next: int = 100
    addr4: ipaddress.IPv4Address = None
    addr6: ipaddress.IPv6Address = None
    worker: SSHDaemonClient = None

@dataclass
class BatchCommand:
    func: Callable = None
    args_lst: list = field(default_factory=list)

def _gs2idx(gs_name):
    return int(gs_name[2:])-1

class StarryNet():

    def __init__(self, configuration_file_path, GS_lat_long, GS_links = None, extra_nodes_links = None):
        # Initialize constellation information.
        sn_args = sn_load_file(configuration_file_path)
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

        self.local_dir = os.path.join(self.configuration_dir, self.experiment_name)
        self._init_local()
        
        # Initialize Observer for topology computation
        self.observer = Observer(configuration_file_path, GS_lat_long, 
                            self.antenna_number, self.elevation)
        
        # Compute topology and get updates
        sat_t_shell, gs_t = self.observer.compute_topology(GS_links)
        self.nodes, self.changes_t = self._process_topo(sat_t_shell, gs_t, extra_nodes_links)

        self._assign_worker([shell[0] for shell in sat_t_shell], sn_args.machine_lst)

        self.events = []
        self.batch_events = [defaultdict(BatchCommand) for _ in range(math.ceil(self.duration))]

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
            for t, (cbf_lst, isls_lst) in enumerate(zip(sat_cbf_t, isls_t)):
                for sat_name, cbf, isls in zip(name_lst, cbf_lst, isls_lst):
                    nodes[sat_name].cbf_t.append((cbf[0], cbf[1], cbf[2]))
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
        for gs_name in gs_name_lst:
            nodes[gs_name] = NodeInfo(name=gs_name, node_type=NodeType.GS, cbf_t=[], links_t=[])
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
                for dst in links:
                    dst_node = nodes.get(dst)
                    if dst_node is None:
                        continue    # single directed
                        # raise ValueError(f"Extra node {name} links to non-existent node {dst}")
                    if dst_node.node_type == NodeType.SAT:
                        raise ValueError(f"Extra node {name} cannot link to satellite {dst}")
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
                timeout=30
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
            print(f'\r{i} / 30', end=' ')
            time.sleep(1)
        print("Routing started!")

    def _worker_for_node(self, node):
        node_info = self.nodes.get(node)
        if node_info is None:
            return None
        return node_info.worker

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

    def list_events(self):
        events = []
        for t, event, *args in sorted(self.events, key=lambda item: item[0]):
            events.append({
                "time": t,
                "kind": "event",
                "name": event.__name__.lstrip('_'),
                "args": args,
            })
        for t, batch_map in enumerate(self.batch_events):
            for name, batch_cmd in batch_map.items():
                for args in batch_cmd.args_lst:
                    events.append({
                        "time": t,
                        "kind": "batch",
                        "name": name,
                        "args": list(args),
                    })
        events.sort(key=lambda item: (item['time'], item['name']))
        return events

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
        def _check_utility(real_t):
            for mid, worker in enumerate(self.worker_lst):
                result = worker.check_utility()
                with open(os.path.join(
                    self.local_dir, f'{real_t}-utility-machine{mid}.txt'), 'w') as f:
                    f.write(result)

        self.events.append((t, _check_utility,))

    def set_damage(self, damaging_ratio, t):
        def _damage(real_t, damaging_ratio):
            damage_lsts = {worker:[] for worker in self.worker_lst}
            cur_num = len(self.undamaged_lst)
            need_damage_num = min(len(self.total_sat_lst) * damaging_ratio, cur_num)
            while(cur_num - len(self.undamaged_lst) < need_damage_num):
                sat = self.undamaged_lst.pop(
                    random.randint(0, len(self.undamaged_lst) - 1)
                )
                worker = self.nodes[sat].worker
                damage_lsts[worker].append(sat)
            for worker, lst in damage_lsts.items():
                worker.damage_nodes(lst)
        self.events.append((t, _damage, damaging_ratio,))

    def set_recovery(self, t):
        def _recovery(real_t):
            for worker in self.worker_lst:
                worker.recover_nodes()
            self.undamaged_lst = self.total_sat_lst.copy()
        self.events.append((t, _recovery,))

    def check_routing_table(self, node, t):
        def _check_route(real_t, node):
            result = self.nodes[node].worker.check_routing_table(node)
            with open(os.path.join(self.local_dir, f'{real_t}-route-{node}.txt'), 'w') as f:
                f.write(result)

        self.events.append((t, _check_route, node,))

    def set_static_route(self, src, dst, next_hop, t):
        def _static_route(worker, args_lst):
            return worker.static_route_batch(args_lst)

        t = self._validate_t(t)
        batch_cmd = self.batch_events[t]['static_route']
        batch_cmd.func = _static_route
        batch_cmd.args_lst.append((src, dst, next_hop))

    def set_netlink(self, node, nlmsg, t):
        def _netlink(worker, args_lst):
            return worker.netlink_batch(args_lst)

        t = self._validate_t(t)
        batch_cmd = self.batch_events[t]['netlink']
        batch_cmd.func = _netlink
        batch_cmd.args_lst.append((node, nlmsg))

    def set_ping(self, src, dst, t, extra_args=[]):
        def _ping(worker, args_lst):
            return worker.ping_batch(args_lst)

        t = self._validate_t(t)
        batch_cmd = self.batch_events[t]['ping']
        batch_cmd.func = _ping
        batch_cmd.args_lst.append((src, dst, extra_args))

    def set_iperf(self, src, dst, t, src_args = [], dst_args = []):
        def _iperf(worker, args_lst):
            return worker.iperf_batch(args_lst)

        t = self._validate_t(t)
        batch_cmd = self.batch_events[t]['iperf']
        batch_cmd.func = _iperf
        batch_cmd.args_lst.append((src, dst, src_args, dst_args))

    def exec_at(self, node, cmd, t):
        def _exec(worker, args_lst):
            return worker.exec_batch(args_lst)

        t = self._validate_t(t)
        batch_cmd = self.batch_events[t]['exec']
        batch_cmd.func = _exec
        batch_cmd.args_lst.append((node, cmd))

    def _event(self, real_t):
        while len(self.events) > 0 and self.events[-1][0] <= real_t:
            event = self.events.pop(-1)
            event[1](real_t, *event[2:])
        while self.last_t <= real_t:
            for batch_cmd in self.batch_events[self.last_t].values():
                node_args = defaultdict(list)
                for args in batch_cmd.args_lst:
                    node_args[self.nodes[args[0]].worker].append(args)
                for worker, args_lst in node_args.items():
                    response = batch_cmd.func(worker, args_lst)

            self.last_t += 1

    def start_emulation(self):
        self.events.sort(key=lambda x:x[0], reverse=True)
        self.last_t = 0

        self.ping_threads = []
        self.iperf_threads = []
        
        start_time = time.time()
        print('Tick event at 0 s')
        self._event(0)

        tid = 1
        while tid < len(self.changes_t):
            t = tid * self.step
            target_time = start_time + t

            now = time.time()
            if now < target_time:
                sleep_time = target_time - now
                print('Sleeping', sleep_time, 's until', t, 's')
                time.sleep(sleep_time)

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

        for ping_thread in self.ping_threads:
            ping_thread.join()
        for iperf_thread in self.iperf_threads:
            iperf_thread.join()

    def clean(self):
        print("Removing containers and links...")
        for worker in self.worker_lst:
            worker.clean()
        print("All containers and links removed.")
