#!/usr/bin/python
# -*- coding: UTF-8 -*-
"""
StarryNet: empowering researchers to evaluate futuristic integrated space and terrestrial networks.
author: Zeqi Lai (zeqilai@tsinghua.edu.cn) and Yangtao Deng (dengyt21@mails.tsinghua.edu.cn)
"""
import time
import threading
import math
import re
import json
import os
import glob
import random
import ipaddress
from enum import Enum
from collections import defaultdict
from typing import List, Tuple, Dict
from dataclasses import dataclass, field
from .sn_observer import *
from .sn_utils import *
from .sn_daemon_client import SSHDaemonClient

EXTRA_LINK_DELAY = 50  # ms, for extra nodes connected to GS

BIRD_CONF_TEXT = """\
log "/var/log/bird.log" { warning, error, auth, fatal, bug };
protocol device {
}
protocol direct {
    disabled;       # Disable by default
    ipv4;           # Connect to default IPv4 table
    ipv6;           # ... and to default IPv6 table
}
protocol kernel {
    ipv4 {          # Connect protocol to IPv4 table by channel
        export all; # Export to protocol. default is export none
    };
}
# protocol static {
#     ipv4;           # Again, IPv6 channel with default options
# }
protocol ospf{
    ipv4 {
        import all;
    };
    area 0 {
    interface "SH*O*S*" {
        type broadcast; # Detected by default
        cost 10;
        hello %d;
    };
    interface "GS*" {
        type broadcast; # Detected by default
        cost 10;
        hello %d;
    };
    interface "POP" {
        type broadcast; # Detected by default
        cost 10;
        hello %d;
    };
    };
}
"""

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
    ifidx_next: int = 10
    addr4: ipaddress.IPv4Address = None
    addr6: ipaddress.IPv6Address = None
    worker: SSHDaemonClient = None

def _gs2idx(gs_name):
    return int(gs_name[2:])-1

class StarryNet():

    def __init__(self, configuration_file_path, GS_lat_long, GS_links = None, extra_nodes_links = None, hello_interval = 5):
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
        self._init_local(hello_interval)
        
        # Initialize Observer for topology computation
        self.observer = Observer(configuration_file_path, GS_lat_long, 
                            self.antenna_number, self.elevation)
        
        # Compute topology and get updates
        sat_t_shell, gs_t = self.observer.compute_topology(GS_links)
        self.nodes, self.changes_t = self._process_topo(sat_t_shell, gs_t, extra_nodes_links)

        self._assign_worker([shell[0] for shell in sat_t_shell], sn_args.machine_lst)

        self.events = []
        self.netlink_events = [list() for _ in range(math.ceil(self.duration))]
        self.cmd_events = [list() for _ in range(math.ceil(self.duration))]
    
    def _init_local(self, hello_interval):
        for txt_file in glob.glob(os.path.join(self.local_dir, '*.txt')):
            os.remove(txt_file)
        for shell in self.shell_lst:
            os.makedirs(os.path.join(self.local_dir, shell['name']), exist_ok=True)
        os.makedirs(os.path.join(self.local_dir, self.gs_dirname), exist_ok=True)
        with open(os.path.join(self.local_dir, 'bird.conf'), 'w') as f:
            f.write(BIRD_CONF_TEXT % (hello_interval, hello_interval, hello_interval))

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
        self.node_mid_dict = node_mid_dict
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

    def run_routing_daemon(self, node_lst='all'):
        print('Initializing routing ...')
        if node_lst == 'all':
            for worker in self.worker_lst:
                worker.init_routing('all')
            print("Routing daemon initialized. Wait 30s for route converged")
        else:
            rtd_lsts = defaultdict(list)
            for name, node in self.nodes.items():
                rtd_lsts[node.worker].append(name)
            for worker, names in rtd_lsts.items():
                worker.init_routing(names)
        
        for i in range(30):
            print(f'\r{i} / 30', end=' ')
            time.sleep(1)
        print("Routing started!")

    # static information
    def get_distance(self, node1, node2, time_index):
        def _get_xyz(node):
            if node.startswith('SH'):
                match = re.search(r'\d+', node)
                shell_id = int(match.group(0))-1
                shell = self.shell_lst[shell_id]
                lla_dict = load_pos(os.path.join(
                    self.local_dir,
                    shell['name'],
                    'position',
                    f'{time_index}.txt'
                ))
                lla = lla_dict[node]
                return to_cbf(lla_dict[node])
            elif node.startswith('GS'):
                return to_cbf(self.gs_lat_long[_gs2idx(node)])
            else:
                raise NotImplementedError

        xyz1, xyz2 = _get_xyz(node1), _get_xyz(node2)
        dx, dy, dz = xyz1[0] - xyz2[0], xyz1[1] - xyz2[1], xyz1[2] - xyz2[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def get_neighbors(self, sat, time_index):
        if not sat.startswith('SH'):
            raise RuntimeError('Not a satellite')
        match = re.search(r'\d+', sat)
        shell_id = int(match.group(0))-1
        shell = self.shell_lst[shell_id]

        isls_dict = load_links_dict(os.path.join(
            self.local_dir,
            shell['name'],
            'isl',
            f'{time_index}-state.txt'
        ))
        neighbors = []
        for isl in isls_dict[sat]:
            neighbors.append(isl[0])
        for name, isl_lst in isls_dict.items():
            for isl  in isl_lst:
                if isl[0] == sat:
                    neighbors.append(name)
        return neighbors

    def get_GSes(self, sat, time_index):
        if not sat.startswith('SH'):
            raise RuntimeError('Not a Satellite')

        gsls_dict = load_links_dict(os.path.join(
            self.local_dir,
            self.gs_dirname,
            'gsl',
            f'{time_index}-state.txt'
        ))
        GSes = []
        for gs, gsl_lst in gsls_dict.items():
            for gsl in gsl_lst:
                if gsl[0] == sat:
                    GSes.append(gs)
        return GSes

    def get_position(self, node, time_index):
        if node.startswith('SH'):
            match = re.search(r'\d+', node)
            shell_id = int(match.group(0))-1
            shell = self.shell_lst[shell_id]
            lla_dict = load_pos(os.path.join(
                self.local_dir,
                shell['name'],
                'position',
                f'{time_index}.txt'
            ))
            return lla_dict[node]
        elif node.startswith('GS'):
            return self.gs_lat_long[_gs2idx(node)]
        else:
            raise NotImplementedError

    def get_IP(self, name):
        node = self.nodes.get(name)
        if node is None:
            return ()
        return node.addr4, node.addr6

    # dynamic events
    def get_utility(self, t):
        def _check_utility(real_t):
            for mid, machine in enumerate(self.worker_lst):
                machine.check_utility(os.path.join(
                    self.local_dir, f'{real_t}-utility-machine{mid}.txt')
                )
        self.events.append((t, _check_utility,))

    def set_damage(self, damaging_ratio, t):
        def _damage(real_t, damaging_ratio):
            damage_lsts = {machine:[] for machine in self.worker_lst}
            cur_num = len(self.undamaged_lst)
            need_damage_num = min(len(self.total_sat_lst) * damaging_ratio, cur_num)
            while(cur_num - len(self.undamaged_lst) < need_damage_num):
                sat = self.undamaged_lst.pop(
                    random.randint(0, len(self.undamaged_lst) - 1)
                )
                machine = self.nodes[sat].worker
                damage_lsts[machine].append(sat)
            for machine, lst in damage_lsts.items():
                machine.damage(lst)
        self.events.append((t, _damage, damaging_ratio,))

    def set_recovery(self, t):
        def _recovery(real_t):
            for machine in self.worker_lst:
                machine.recovery(self.sat_loss)
            self.undamaged_lst = self.total_sat_lst.copy()
        self.events.append((t, _recovery,))

    def check_routing_table(self, node, t):
        def _check_route(real_t, node):
            self.nodes[node].worker.check_route(
                os.path.join(self.local_dir, f'{real_t}-route-{node}.txt'),
                node
            )
        self.events.append((t, _check_route, node,))

    def set_next_hop(self, src, dst, next_hop, t):
        def _set_next_hop(real_t, src, dst, next_hop):
            self.nodes[src].worker.sr(src, dst, next_hop)
        if src in self.nodes and dst in self.nodes:
            self.events.append((t, _set_next_hop, src, dst, next_hop))
        else:
            raise ValueError('Specified node not found')

    def set_static_routes_batch(self, routes_config, t):
        """Set static routes for multiple nodes at specified time
        
        Args:
            routes_config: Dictionary mapping node names to lists of route tuples
                          Each tuple: (dst, gw, dev, metric)
            t: Time when the batch routes should be applied
        """
        def _set_static_routes_batch(real_t, routes_config):
            # Group routes by worker machine to minimize communication
            worker_routes = defaultdict(list)
            
            for node_name, routes in routes_config.items():
                node=self.nodes.get(node_name)
                if node is None:
                    continue
                worker_routes[node.worker].append((node_name, routes))

            for worker, node_routes_lst in worker_routes.items():
                worker.sr_batch(node_routes_lst)
        
        self.events.append((t, _set_static_routes_batch, routes_config))

    def set_netlink_route(self, node, nlmsg, t):
        if t >= self.duration:
            t = round(self.duration) - 1
        elif t < 0:
            t = 0
        else:
            t = round(t)
        self.cmd_events[t].append((node, nlmsg))
    
    def _netlink_route(self, route_lst):
        worker_msgs = defaultdict(list)
        for node, nlmsg in route_lst:
            worker_msgs[self.nodes[node].worker].append((node, nlmsg))
        for worker, routes in worker_msgs.items():
            worker.netlink(routes)

    def set_ping(self, src, dst, t):
        def _ping(real_t, src, dst):
            self.ping_threads.append(self.nodes[src].worker.ping_async(
                os.path.join(self.local_dir, f'{real_t}-ping-{src}-{dst}.txt'),
                src, dst
            ))
        self.events.append((t, _ping, src, dst))

    def set_iperf(self, src, dst, t, extra_args = []):
        if t >= self.duration:
            t = round(self.duration) - 1
        elif t < 0:
            t = 0
        else:
            t = round(t)
        self.cmd_events[t].append((src, dst, extra_args))
    
    def _iperf(self, cmd_lst):
        node_cmds = defaultdict(list)
        for src, dst, extra_args in cmd_lst:
            node_cmds[self.nodes[src].worker].append([src, dst, *extra_args])
        for node, cmds in node_cmds.items():
            node.iperf(cmds)

    def exec_at(self, node, cmd, t):
        def _exec(real_t, node, cmd):
            self.nodes[node].worker.exec(node, cmd)
        self.events.append((t, _exec, node, cmd))

    def exec_now(self, node, cmd):
        self.nodes[node].worker.exec(node, cmd)

    def print_all_nodes(self, path):
        with open(path, 'w') as f:
            for machine in self.worker_lst:
                machine.print_nodes(f)

    def _event(self, real_t):
        while len(self.events) > 0 and self.events[-1][0] <= real_t:
            event = self.events.pop(-1)
            event[1](real_t, *event[2:])
        while self.last_t <= real_t:
            self._netlink_route(self.netlink_events[self.last_t])
            self._iperf(self.cmd_events[self.last_t])
            self.last_t += 1

    def start_emulation(self):
        self.events.sort(key=lambda x:x[0], reverse=True)
        self.last_t = 0

        self.ping_threads = []
        self.iperf_threads = []
        t = 0.0
        tid = 1
        while t < self.duration:
            start = time.time()
            print("Update networks using pre-computed topology...")
            if tid < self.duration:
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
            print("\nTrigger events at", t, "s ...")
            self._event(t)
            end = time.time()
            print(end-start, "s elapsed,", update_end-start, "s for network update")
            if end - start < 1:
                print('Sleep', 1 + start - end, 's')
                time.sleep(1 + start - end)
            t += self.step
            tid += 1
        for ping_thread in self.ping_threads:
            ping_thread.join()
        for iperf_thread in self.iperf_threads:
            iperf_thread.join()

    def clean(self):
        print("Removing containers and links...")
        for worker in self.worker_lst:
            worker.clean()
        print("All containers and links workerd.")
