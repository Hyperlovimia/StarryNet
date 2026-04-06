#!/usr/bin/python3
import os
import subprocess
import sys
import time
import socket
import ipaddress
import threading
import queue
from dataclasses import dataclass
from typing import Dict, List, Tuple
from collections import defaultdict
# from line_profiler import LineProfiler

module_dir = os.path.dirname(__file__)
try:
    import pyctr
except ModuleNotFoundError:
    subprocess.check_call(
        f"cd {module_dir} && "
        "gcc $(python3-config --cflags --ldflags) "
        "-shared -fPIC -O2 pyctr.c -o pyctr.so",
        shell=True
    )
    import pyctr
PRELOAD_PATH = os.path.join(os.path.dirname(__file__), 'libpreload.so')

class NetworkManageSession:

    def __init__(self, node_dir, name):
        sock_path = os.path.abspath(f'{node_dir}/rootfs/{name}')
        self.sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sk.connect(sock_path)

    def _ensure_ack(self, ack_nr):
        acked = 0
        while acked < ack_nr:
            chunk = self.sk.recv(2 - acked)
            if not chunk:
                break
            acked += len(chunk)

    def shutdown(self):
        self.sk.close()

    def register_if(self, if_idx):
        self.sk.send(f'A {if_idx}\n'.encode())
        self._ensure_ack(1)

    def connect_peer(self, if_idx, peer_name, peer_if_idx):
        self.sk.send(f'L {if_idx} {peer_name} {peer_if_idx}\n'.encode())
        self._ensure_ack(1)

    def if_up(self, if_idx):
        self.sk.send(f'X {if_idx} 1\n'.encode())
        self._ensure_ack(1)

    def modify_addr(self, is_add, if_idx, addr4str, addr6str):
        self.sk.send(f'I {if_idx} {addr4str} {addr6str}\n'.encode())
        self._ensure_ack(1)

    def traffic_control(self, if_idx, delay, bw, loss):
        self.sk.send(f'U {if_idx} {delay} {loss} {bw}\n'.encode())
        self._ensure_ack(1)

    def disconnect_peer(self, if_idx):
        self.sk.send(f'X {if_idx} 0\n'.encode())
        self.sk.send(f'D {if_idx}\n'.encode())

    def modify_routes(self, routes):
        raise NotImplementedError

@dataclass
class NetInterface:
    if_idx: int
    ipv4: ipaddress.IPv4Interface = None
    ipv6: ipaddress.IPv6Interface = None

class Node:
    """Node object representing a network node in the orchestrator"""
    
    def __init__(self, name: str, node_dir: str, node_id: int = 0):
        self.name = name
        self.node_dir = node_dir
        self.node_id = node_id
        self.pid = pyctr.container_run(node_dir, name, PRELOAD_PATH)
        self.session: NetworkManageSession = None
        self.idle_links: List[NetInterface] = list()
        self.peer2link: Dict[str, NetInterface] = dict()
        self.ifidx_next = 3

    def __lt__(self, other):
        return self.pid < other.pid

    def __del__(self):
        """Destructor to cleanup resources"""
        try:
            if self.session:
                self.session.shutdown()
            os.kill(self.pid, 9)
        except:
            pass  # Ignore errors during cleanup
    
    def _ensure_session(self):
        if self.session is None:
            self.session = NetworkManageSession(self.node_dir, self.name)

    def init_loopback(self):
        self._ensure_session()

        addr4 = ipaddress.IPv4Interface(
            f"16.{(self.node_id >> 8) & 0xFF}.{self.node_id & 0xFF}.1/32")
        addr6 = ipaddress.IPv6Interface(
            f"2000::{self.node_id:04x}/128"
        )
        lo_link = NetInterface(1, addr4, addr6)

        self.session.modify_addr(True, lo_link.if_idx, addr4.compressed, addr6.compressed)
        self.session.if_up(lo_link.if_idx)

        self.peer2link['lo'] = lo_link
        return addr4.compressed, addr6.compressed
    
    def register_if(self, peer_name):
        if len(self.idle_links) > 0:
            new_link = self.idle_links.pop()
        else:
            self._ensure_session()
            self.session.register_if(self.ifidx_next)
            new_link = NetInterface(if_idx=self.ifidx_next)
            self.ifidx_next += 1

        self.peer2link[peer_name] = new_link
        return new_link.if_idx

    def connect_if(self, peer_name: str, peer_if_idx: int):
        self._ensure_session()
        link = self.peer2link[peer_name]
        self.session.connect_peer(link.if_idx, peer_name, peer_if_idx)

    def init_if(self, peer_name: str, addr4: str, addr6: str, delay: str, bw: str, loss: str):
        link = self.peer2link.get(peer_name)
        if link is None:
            return

        addr4 = ipaddress.IPv4Interface(addr4)
        addr6 = ipaddress.IPv6Interface(addr6)
        self._ensure_session()
        self.session.modify_addr(True, link.if_idx, addr4.compressed, addr6.compressed)
        self.session.traffic_control(link.if_idx, delay, bw, loss)
        self.session.if_up(link.if_idx)
        link.ipv4 = addr4
        link.ipv6 = addr6

    def update_if(self, peer_name: str, delay: str, bw: str, loss: str):
        link = self.peer2link.get(peer_name)
        if link is None:
            return

        self._ensure_session()
        self.session.traffic_control(link.if_idx, delay, bw, loss)

    def modify_routes(self, routes):
        self._ensure_session()
        self.session.modify_routes(routes)

    def del_if(self, peer_name: str):
        link = self.peer2link.pop(peer_name, None)
        if link is None:
            return

        self._ensure_session()
        self.session.disconnect_peer(link.if_idx)
        self.idle_links.append(link)

    def run_command(self, command, *args, **kwargs):
        return subprocess.Popen(
            ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', str(self.pid), *command),
            *args, **kwargs
        )

class OrchestratorContext:
    """Context object to maintain state for orchestrator"""
    
    def __init__(self, workdir):
        self.workdir = workdir
        self.damage_dict = {}

        self.nodes: Dict[str, Node] = {}

        self.cmd_to_start = queue.PriorityQueue()
        self.cmd_cnt_dict = defaultdict(int)
        self.cmd_pending = set()
        threading.Thread(target=self._check_commands, daemon=True).start()

    def _check_commands(self):
        cur = None
        while True:
            time.sleep(0.1)
            now = time.perf_counter()

            if cur is None:
                try:
                    cur = self.cmd_to_start.get(block=False)
                except queue.Empty:
                    pass

            while cur is not None and cur[0] <= now:
                _, node, cmdline = cur
                self.cmd_cnt_dict[node.name] += 1
                cmd_id = self.cmd_cnt_dict[node.name]
                fd = os.open(
                    f'{self.workdir}/cmd_{node.name}_{cmd_id}_{cmdline[0]}.out',
                    os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                )
                os.write(fd, f"{now}: {' '.join(cmdline)}\n".encode())
                proc = node.run_command(cmdline, stdout=fd, stderr=subprocess.STDOUT)
                os.close(fd)
                self.cmd_pending.add(proc)
                try:
                    cur = self.cmd_to_start.get(False)
                except queue.Empty:
                    cur = None

            finished = []
            for proc in self.cmd_pending:
                if proc.poll() is None:
                    continue
                finished.append(proc)
            for proc in finished:
                self.cmd_pending.remove(proc)

    def clean(self):
        for node in self.nodes.values():
            del node
        
        self.nodes.clear()
        self.damage_dict.clear()

    def init_nodes(self, base_dir, node_configs):
        self.clean()

        for node_name, node_id in node_configs.items():
            node_dir = f"{base_dir}/overlay/{node_name}"
            os.makedirs(node_dir, exist_ok=True)
            self.nodes[node_name] = Node(node_name, node_dir, node_id=node_id)

        time.sleep(5)
        node_addrs = {}
        for node_name, node in self.nodes.items():
            node_addrs[node_name] = node.init_loopback()

        return node_addrs

    def add_link_intra_machine(self,
            name1: str, name2: str,
            src_addr4: str, src_addr6: str,
            dst_addr4: str, dst_addr6,
            delay: str, bw: str, loss: str
        ):
        node1 = self.nodes.get(name1)
        node2 = self.nodes.get(name2)
        if node1 is None or node2 is None:
            return

        print('add', name1, name2)
        if_idx1 = node1.register_if(name2)
        if_idx2 = node2.register_if(name1)
        node1.connect_if(name2, if_idx2)
        node2.connect_if(name1, if_idx1)
        node1.init_if(name2, src_addr4, src_addr6, delay, bw, loss)
        node2.init_if(name1, dst_addr4, dst_addr6, delay, bw, loss)

    def add_link_inter_machine(self,
            name1: str, name2: str,
            remote_ip: str, addr4: str, addr6: str,
            delay: str, bw: str, loss: str
        ):
        raise NotImplementedError
        node1 = self.nodes.get(name1)
        if node1 is None:
            return

        node1.init_if(name2, addr4, addr6, delay, bw, loss)

    def update_if(self, node_name: str, ifname: str, delay: str, bw: str, loss: str):
        node = self.nodes.get(node_name)
        if node is None:
            return

        node.update_if(ifname, delay, bw, loss)

    def del_if(self, node_name: str, ifname: str):
        node = self.nodes.get(node_name)
        if node is None:
            return

        node.del_if(ifname)

    def init_route_daemons(self, conf_path: str, nodes: str):
        bird_ctl_path = conf_path[:conf_path.rfind('/')] + '/bird.ctl'
        if nodes == 'all':
            nodes_lst = self.nodes.keys()
        else:
            nodes_lst = nodes.split(',')

        for node_name in nodes_lst:
            node = self.nodes.get(node_name)
            if node is None:
                continue
            proc = node.run_command(('bird', '-c', conf_path, '-s', bird_ctl_path))
            proc.wait()

    def ping(self, src: str, dst: str):
        src_node = self.nodes.get(src)
        dst_node = self.nodes.get(dst)
        if src_node is None or dst_node is None:
            return
        
        dst_addr_lst = subprocess.check_output(
            ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', dst_node.pid,
            'ip', '-br', 'addr', 'show')
        ).decode().splitlines()
        for dev_state_addrs in dst_addr_lst:
            dev_state_addrs = dev_state_addrs.split()
            if dev_state_addrs[0] == 'lo':
                continue
            dst_addr = dev_state_addrs[2]
            if dev_state_addrs[0].split('@')[0] == src:
                break
        dst_addr = dst_node.loopback_ipv4.ip.compressed

        subprocess.run(
            ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', src_node.pid,
             'ping', '-c', '4', '-i', '0.01', dst_addr),
             stdout=sys.stdout, stderr=subprocess.STDOUT
        )

    def iperf(self, cmds):
        time_point = time.perf_counter()
        for cmd in cmds:
            src_node = self.nodes.get(cmd[0])
            dst_node = self.nodes.get(cmd[1])
            if src_node is None or dst_node is None:
                continue

            dst_addr = dst_node.loopback_ipv4.ip.compressed
            self.cmd_to_start.put((time_point, dst_node, ('iperf3', '-s')))
            self.cmd_to_start.put((time_point + 0.5, src_node, ('iperf3', '-c', dst_addr, *cmd[2:])))

    def exec(self, node_name: str, cmd: str):
        """Execute command in node using context"""
        node = self.nodes.get(node_name)
        if node is None:
            return None
        
        return subprocess.run(
            'nsenter -m -u -i -n -p -t ' + str(node.pid) + ' ' + cmd,
            shell=True,
            capture_output=True,
            text=True
        )

    def check_route(self, node_name: str):
        node = self.nodes.get(node_name)
        if node is None:
            print(f"Node {node_name} not found")
            return

        subprocess.run(
            ('nsenter', '-n', '-t', node.pid,
            'route'),
            stdout=sys.stdout, stderr=subprocess.STDOUT
        )

    def damage(self, random_list: List[str]):
        raise NotImplementedError
        for node_name in random_list:
            node = self.nodes.get(node_name)
            if node is None:
                print(f"Node {node_name} not found")
                continue
            
            out = subprocess.check_output(
                ('ip', '-br', 'addr', 'show')).decode()
            dev_lst = []

            for line in out.splitlines():
                line = line.strip()
                if len(line) == 0 or line.startswith('lo'):
                    continue
                toks = line.split()
                dev_name = toks[0].split('@')[0]
                addr = None
                for tok in toks[1:]:
                    if ':' in tok:
                        # found first ip6 addr
                        addr = ipaddress.IPv6Interface(tok)
                        break
                node.session.if_down(dev_name)
                dev_lst.append((dev_name, addr))
            
            self.damage_dict[node] = dev_lst

    def recover(self, sat_loss: str):
        raise NotImplementedError
        if not self.damage_dict:
            return

        for node_name, dev_lst in self.damage_dict.items():
            node = self.nodes.get(node_name)
            if node is None:
                continue

            for dev_name, addr in dev_lst:
                node.session.if_up(dev_name)
                node.session.modify_addr(True, dev_name, addr.ip.packed, addr.network.prefixlen)

        self.damage_dict.clear()

