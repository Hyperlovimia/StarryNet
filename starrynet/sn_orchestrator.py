#!/usr/bin/python3
import os
import subprocess
import time
import socket
import ipaddress
import threading
from typing import Dict, List, Optional

try:
    import pyctr
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "StarryNet C extension pyctr is not installed. "
        "Reinstall the package or rebuild the extension before running."
    ) from exc


MODULE_DIR = os.path.dirname(__file__)
REPO_DIR = os.path.dirname(MODULE_DIR)


def _resolve_backend_path(env_name, *candidates):
    env_path = os.environ.get(env_name)
    if env_path:
        return env_path
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0]


PRELOAD_PATH = _resolve_backend_path(
    'STELLARNET_PRELOAD_PATH',
    os.path.join(MODULE_DIR, 'libpreload.so'),
    os.path.join(REPO_DIR, 'stellarnet', 'libpreload.so'),
)
LIB_PATH = _resolve_backend_path(
    'STELLARNET_LIB_PATH',
    os.path.join(MODULE_DIR, 'liblkl-posix.so'),
    os.path.join(REPO_DIR, 'stellarnet', 'liblkl-posix.so'),
)


class NetworkManageSession:
    def __init__(self, node_dir, name):
        sock_path = os.path.abspath(f'{node_dir}/rootfs/{name}')
        self.sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sk.connect(sock_path)

    def shutdown(self):
        self.sk.close()

    def _readline(self):
        data = bytearray()
        while not data.endswith(b'\n'):
            chunk = self.sk.recv(1)
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)

    def _read_int(self):
        response = self._readline().strip()
        if not response:
            raise RuntimeError("backend did not return a response")
        return int(response)

    def _expect_ok(self, command):
        result = self._read_int()
        if result < 0:
            raise RuntimeError(f"backend command {command} failed: {result}")
        return result

    def register_if(self):
        self.sk.send(b'A\n')
        if_idx = self._read_int()
        if if_idx < 0:
            raise RuntimeError("backend failed to register NIC")
        return if_idx

    def connect_peer(self, if_idx, peer_name, peer_if_idx):
        self.sk.send(f'L {if_idx} {peer_name} {peer_if_idx}\n'.encode())
        self._expect_ok('L')

    def if_up(self, if_idx):
        self.sk.send(f'X {if_idx} 1\n'.encode())
        self._expect_ok('X')

    def if_down(self, if_idx):
        self.sk.send(f'X {if_idx} 0\n'.encode())
        self._expect_ok('X')

    def modify_addr(self, if_idx, addr4str, addr6str):
        self.sk.send(f'I {if_idx} {addr4str} {addr6str}\n'.encode())
        self._expect_ok('I')

    def traffic_control(self, if_idx, delay, bw, loss):
        self.sk.send(f'U {if_idx} {delay} {loss} {bw}\n'.encode())
        self._expect_ok('U')

    def disconnect_peer(self, if_idx):
        self.sk.send(f'X {if_idx} 0\n'.encode())
        self._expect_ok('X')
        self.sk.send(f'D {if_idx}\n'.encode())
        self._expect_ok('D')


class ManagedProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: Optional[int] = None

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        try:
            waited_pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.returncode = 0
            return self.returncode
        if waited_pid == 0:
            return None
        self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self):
        if self.returncode is not None:
            return self.returncode
        try:
            _, status = os.waitpid(self.pid, 0)
            self.returncode = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            self.returncode = 0
        return self.returncode


class NetInterface:
    def __init__(self, if_idx: int, ipv4: ipaddress.IPv4Interface = None, ipv6: ipaddress.IPv6Interface = None):
        self.if_idx = if_idx
        self.ipv4 = ipv4
        self.ipv6 = ipv6


class Node:
    def __init__(self, name: str, node_dir: str, node_id: int = 0):
        self.name = name
        self.node_dir = node_dir
        self.node_id = node_id
        self.pid = pyctr.container_run(node_dir, name, PRELOAD_PATH, LIB_PATH)
        self.session: Optional[NetworkManageSession] = None
        self.idle_links: List[NetInterface] = []
        self.peer2link: Dict[str, NetInterface] = {}
        self._exec_lock = threading.Lock()

    def __lt__(self, other):
        return self.pid < other.pid

    def __del__(self):
        try:
            if self.session:
                self.session.shutdown()
            os.kill(self.pid, 9)
        except Exception:
            pass

    def _ensure_session(self):
        if self.session is None:
            self.session = NetworkManageSession(self.node_dir, self.name)

    def init_loopback(self):
        self._ensure_session()

        addr4 = ipaddress.IPv4Interface(
            f"16.{(self.node_id >> 8) & 0xFF}.{self.node_id & 0xFF}.1/32")
        addr6 = ipaddress.IPv6Interface(f"2000::{self.node_id:04x}/128")
        lo_link = NetInterface(1, addr4, addr6)

        self.session.modify_addr(lo_link.if_idx, addr4.compressed, addr6.compressed)
        self.session.if_up(lo_link.if_idx)
        self.peer2link['lo'] = lo_link
        return addr4.compressed, addr6.compressed

    def register_if(self, peer_name: str):
        self._ensure_session()
        if self.idle_links:
            link = self.idle_links.pop()
            link.ipv4 = None
            link.ipv6 = None
        else:
            link = NetInterface(self.session.register_if())
        self.peer2link[peer_name] = link
        return link.if_idx

    def connect_if(self, peer_name: str, peer_if_idx: int):
        self._ensure_session()
        link = self.peer2link.get(peer_name)
        if link is None:
            return
        self.session.connect_peer(link.if_idx, peer_name, peer_if_idx)

    def init_if(self, peer_name: str, addr4: str, addr6: str, delay: str, bw: str, loss: str):
        link = self.peer2link.get(peer_name)
        if link is None:
            return

        addr4 = ipaddress.IPv4Interface(addr4)
        addr6 = ipaddress.IPv6Interface(addr6)
        self._ensure_session()
        self.session.modify_addr(link.if_idx, addr4.compressed, addr6.compressed)
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

    def del_if(self, peer_name: str):
        link = self.peer2link.pop(peer_name, None)
        if link is None:
            return
        self._ensure_session()
        self.session.disconnect_peer(link.if_idx)
        self.idle_links.append(link)

    def run_command(self, command, stdout=None, stderr=None):
        cmdline = tuple(arg.encode() for arg in command)
        with self._exec_lock:
            saved_stdout = os.dup(1) if stdout is not None else None
            saved_stderr = os.dup(2) if stderr is not None else None
            try:
                if stdout is not None:
                    os.dup2(stdout, 1)
                if stderr is not None and stderr != subprocess.STDOUT:
                    os.dup2(stderr, 2)
                elif stderr == subprocess.STDOUT and stdout is not None:
                    os.dup2(stdout, 2)
                pid = pyctr.container_exec(
                    self.pid, self.name, PRELOAD_PATH, LIB_PATH, cmdline
                )
            finally:
                if saved_stdout is not None:
                    os.dup2(saved_stdout, 1)
                    os.close(saved_stdout)
                if saved_stderr is not None:
                    os.dup2(saved_stderr, 2)
                    os.close(saved_stderr)
        return ManagedProcess(pid)


class OrchestratorContext:
    def __init__(self, workdir):
        self.workdir = workdir
        self.nodes: Dict[str, Node] = {}
        self.damage_lst: List[Node] = []

    def clean(self):
        for node in self.nodes.values():
            del node
        self.nodes.clear()
        self.damage_lst.clear()

    def init_nodes(self, base_dir, node_configs):
        self.clean()
        for node_name, node_id in node_configs.items():
            node_dir = f"{base_dir}/overlay/{node_name}"
            os.makedirs(node_dir, exist_ok=True)
            self.nodes[node_name] = Node(node_name, node_dir, node_id=node_id)

        time.sleep(5)
        return {
            node_name: node.init_loopback()
            for node_name, node in self.nodes.items()
        }

    def add_link_intra_machine(
        self,
        name1: str, name2: str,
        src_addr4: str, src_addr6: str,
        dst_addr4: str, dst_addr6: str,
        delay: str, bw: str, loss: str,
    ):
        node1 = self.nodes.get(name1)
        node2 = self.nodes.get(name2)
        if node1 is None or node2 is None:
            return

        src_ifidx = node1.register_if(name2)
        dst_ifidx = node2.register_if(name1)
        node1.connect_if(name2, dst_ifidx)
        node2.connect_if(name1, src_ifidx)
        node1.init_if(name2, src_addr4, src_addr6, delay, bw, loss)
        node2.init_if(name1, dst_addr4, dst_addr6, delay, bw, loss)

    def add_link_inter_machine(
        self,
        name1: str, name2: str,
        remote_ip: str,
        addr4: str, addr6: str,
        delay: str, bw: str, loss: str,
    ):
        raise NotImplementedError("StellarNet inter-machine links are not implemented yet")

    def init_route_daemons(self, conf_path: str, nodes: str):
        conf_path = os.path.abspath(conf_path)
        ctl_path = os.path.join(os.path.dirname(conf_path), 'bird.ctl')
        nodes_lst = self.nodes.keys() if nodes == 'all' else nodes.split(',')

        for node_name in nodes_lst:
            node = self.nodes.get(node_name)
            if node is None:
                continue
            proc = node.run_command(('bird', '-c', conf_path, '-s', ctl_path))
            proc.wait()

    def set_static_route(self, src: str, dst: str, next_hop: str):
        src_node = self.nodes.get(src)
        dst_node = self.nodes.get(dst)
        next_hop_node = self.nodes.get(next_hop)
        if src_node is None or dst_node is None or next_hop_node is None:
            return

        dst_addr = dst_node.peer2link['lo'].ipv4.ip.compressed
        next_hop_link = next_hop_node.peer2link.get(src)
        if next_hop_link is None or next_hop_link.ipv4 is None:
            return
        via_addr = next_hop_link.ipv4.ip.compressed
        proc = src_node.run_command((
            'ip', 'route', 'replace', f'{dst_addr}/32', 'via', via_addr
        ))
        proc.wait()

    def get_ping_command(self, src: str, dst: str, extra_args: List[str] = []):
        src_node = self.nodes.get(src)
        dst_node = self.nodes.get(dst)
        if src_node is None or dst_node is None:
            return None

        dst_addr = dst_node.peer2link['lo'].ipv4.ip.compressed
        return src_node, ('ping', '-c', '4', '-i', '0.01', *extra_args, dst_addr)

    def get_iperf_commands(self, src: str, dst: str, src_args: List[str] = [], dst_args: List[str] = []):
        src_node = self.nodes.get(src)
        dst_node = self.nodes.get(dst)
        if src_node is None or dst_node is None:
            return None

        dst_addr = dst_node.peer2link['lo'].ipv4.ip.compressed
        return (
            (dst_node, ('iperf3', '-s', '-1', *dst_args)),
            (src_node, ('iperf3', '-c', dst_addr, *src_args)),
        )

    def get_exec_command(self, node_name: str, cmd: str):
        node = self.nodes.get(node_name)
        if node is None:
            return None
        return node, ('sh', '-lc', cmd)

    def netlink(self, routes):
        raise NotImplementedError("Raw netlink injection is not available on the StellarNet backend")

    def check_route(self, node_name: str):
        node = self.nodes.get(node_name)
        if node is None:
            return ''

        output_path = os.path.join(self.workdir, f'route-{node_name}.txt')
        fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        try:
            task = node.run_command(('ip', 'route'), stdout=fd, stderr=subprocess.STDOUT)
            task.wait()
        finally:
            os.close(fd)
        with open(output_path, 'r') as f:
            return f.read()

    def damage(self, random_list: List[str]):
        for node_name in random_list:
            node = self.nodes.get(node_name)
            if node is None:
                continue
            for peer_name, link in node.peer2link.items():
                if peer_name == 'lo':
                    continue
                node.session.if_down(link.if_idx)
            self.damage_lst.append(node)

    def recover(self):
        for node in self.damage_lst:
            for peer_name, link in node.peer2link.items():
                if peer_name == 'lo':
                    continue
                try:
                    node.session.if_up(link.if_idx)
                except Exception:
                    pass
        self.damage_lst.clear()

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
