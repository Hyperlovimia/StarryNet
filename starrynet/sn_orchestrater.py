#!/usr/bin/python3
import os
import subprocess
import sys
import json
import glob
import ctypes
import socket

# C module
try:
    import pyctr
except ModuleNotFoundError:
    subprocess.check_call(
        "cd " + os.path.dirname(__file__) + " && "
        "gcc $(python3-config --cflags --ldflags)"
        "-shared -fPIC -O2 pyctr.c -o pyctr.so",
        shell=True
    )
    import pyctr


"""
Used in the remote machine for link updating, initializing links, damaging and recovering links and other functionalities。
author: Yangtao Deng (dengyt21@mails.tsinghua.edu.cn) and Zeqi Lai (zeqilai@tsinghua.edu.cn) 
"""

ASSIGN_FILENAME = 'assign.json'
PID_FILENAME = 'container_pid.txt'
DAMAGE_FILENAME = 'damage_list.txt'
PRELOAD_PATH = os.path.join(os.path.dirname(__file__), 'libpreload.so')

NOT_ASSIGNED = 'NA'
VXLAN_PORT = '4789'
# FIXME
CLONE_NEWNET = 0x40000000
libc = ctypes.CDLL(None)
main_net_fd = os.open('/proc/self/ns/net', os.O_RDONLY)

def _pid_map(pid_path, pop = False):
    global _pid_map_cache
    if _pid_map_cache is None:
        _pid_map_cache = {}
        if not os.path.exists(pid_path):
            print('Error: container index file not found, please create nodes')
            exit(1)
        with open(pid_path, 'r') as f:
            for line in f:
                if len(line) == 0 or line.isspace():
                    continue
                for name_pid in line.strip().split():
                    if name_pid == NOT_ASSIGNED:
                        continue
                    name_pid = name_pid.split(':')
                    _pid_map_cache[name_pid[0]] = name_pid[1]
    if pop:
        ret = _pid_map_cache
        _pid_map_cache = None
        return ret
    return _pid_map_cache

def _get_params(path):
    with open(path, 'r') as f:
        obj = json.load(f)
        shell_num = obj['shell_num']
        node_mid_dict = obj['node_mid_dict']
        ip_lst = obj['ip']
    return shell_num, node_mid_dict, ip_lst

def _parse_links(path):
    disc_lst, update_lst, conn_lst, add_lst = [], [], [], []
    f = open(path, 'r')
    for line in f:
        grps = line.strip().split('|')
        node = grps[0]
        for grp, links in zip(grps[1:], [disc_lst, update_lst, conn_lst, add_lst]):
            if len(grp) == 0:
                continue
            for link in grp.split(' '):
                attr = link.split(',')
                links.append((node, *attr))

    f.close()
    return disc_lst, update_lst, conn_lst, add_lst

def _sock_path(dir, name):
    return f'{dir}/overlay/{name}/rootfs/{name}'

def _disconnect_link(dir, node, nic_idx):
    sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sk.connect(_sock_path(dir, node))
    sk.send(f'X {nic_idx} 0\n'.encode())
    sk.send(f'D {nic_idx}\n'.encode())
    acked = 0
    while acked < 2:
        chunk = sk.recv(2 - acked)
        if not chunk:
            break
        acked += len(chunk)
    sk.close()

def _update_if(dir, node, nic_idx, delay, bw, loss):
    return
    # sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # sk.connect(_sock_path(dir, node))
    # sk.send(f'U {nic_idx} {delay} {bw} {loss}\n'.encode())
    # sk.recv(1)
    # sk.close()

def _add_link(dir, node, nic_idx):
    sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sk.connect(_sock_path(dir, node))
    sk.send(f'A {nic_idx}\n'.encode())
    sk.recv(1)
    sk.close()

def _conncect_intra_machine(dir, node, nic_idx, peer, peer_idx, ip4, ip6, delay, bw, loss):
    sk = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sk.connect(_sock_path(dir, node))
    sk.send(f'L {nic_idx} {peer} {peer_idx}\n'.encode())
    # sk.send(f'U {nic_idx} {delay} {bw} {loss}\n'.encode())
    sk.send(f'I {nic_idx} {ip4} {ip6}\n'.encode())
    sk.send(f'X {nic_idx} 1\n'.encode())
    acked = 0
    while acked < 3:
        chunk = sk.recv(3 - acked)
        if not chunk:
            break
        acked += len(chunk)
    sk.close()

def sn_init_nodes(dir, shell_num, node_mid_dict):
    pid_file = open(dir + '/' + PID_FILENAME, 'w', encoding='utf-8')
    sat_cnt = 0
    for node, mid in node_mid_dict.items():  
        if mid != machine_id:
            pid_file.write(NOT_ASSIGNED + ' ')
            continue
        node_dir = f"{dir}/overlay/{node}"
        sat_cnt += 1
        os.makedirs(node_dir, exist_ok=True)
        pid_file.write(node+':'+str(pyctr.container_run(node_dir, node, PRELOAD_PATH))+' ')
    pid_file.write('\n')
    print(f'[{machine_id}]: {sat_cnt} nodes initialized')
    pid_file.close()

def sn_update_network(
        dir, ts, shell_num, node_mid_dict, ip_lst,
        isl_bw, isl_loss, gsl_bw, gsl_loss
    ):
    paths = [f"{dir}/shell{shell_id}" for shell_id in range(shell_num)] + [f"{dir}/GS"]
    bw_losses = [(isl_bw, isl_loss)] * shell_num + [(gsl_bw, gsl_loss)]
    addrs = [('10', '2001')] * shell_num + [('9', '2002')]
    grp_names = [f"Shell-{shell_id+1}" for shell_id in range(shell_num)] + ["GS"]
    for path, (bw, loss), (p4, p6), gname in zip(paths, bw_losses, addrs, grp_names):
        if not os.path.exists(path):
            continue
        disc_cnt, update_cnt, conn_cnt = 0, 0, 0
        disc_lst, update_lst, conn_lst, add_lst = _parse_links(f"{path}/{ts}.txt")
        for node, nic in disc_lst:
            if node_mid_dict[node] == machine_id:
                disc_cnt += 1
                _disconnect_link(dir, node, nic)
        for node, peer, delay, nic in update_lst:
            if node_mid_dict[node] == machine_id:
                update_cnt += 1
                _update_if(dir, node, nic, delay, bw, loss)
        for node, nic in add_lst:
            if node_mid_dict[node] == machine_id:
                _add_link(dir, node, nic)
        for node, peer, delay, idx, nic, peer_nic in conn_lst:
            idx = int(idx)
            if node < peer:
                ip4 = f'{p4}.{idx >> 8}.{idx & 0xFF}.10/24'
                ip6 = f'{p6}:{idx >> 8}:{idx & 0xFF}::10/48'
            else:
                ip4 = f'{p4}.{idx >> 8}.{idx & 0xFF}.40/24'
                ip6 = f'{p6}:{idx >> 8}:{idx & 0xFF}::40/48'
            if node_mid_dict[node] == machine_id:
                conn_cnt += 1
                _conncect_intra_machine(
                    dir, node, nic, peer, peer_nic, ip4, ip6,
                    delay, bw, loss
                )
        print(f"[{machine_id}] {gname}:",
              f"{disc_cnt} disconnected, {update_cnt} updated, {conn_cnt} connected")

def sn_container_check_call(pid, cmd, *args, **kwargs):
    subprocess.check_call(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', pid, *cmd),
        *args, **kwargs
    )

def sn_container_run(pid, name, cmd):
    pyctr.container_exec(
        int(pid),
        name,
        PRELOAD_PATH,
        [arg.encode() for arg in cmd],
        False,
    )

def sn_container_check_output(pid, cmd, *args, **kwargs):
    return subprocess.check_output(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', pid, *cmd),
        *args, **kwargs
    )

def sn_operate_every_node(dir, func, *args):
    pid_map = _pid_map(dir + '/' + PID_FILENAME)
    for name, pid in pid_map.items():
        func(pid, name, *args)

def get_IP(dir, node):
    pid = _pid_map(f"{dir}/{PID_FILENAME}")[node]
    addr_lst = subprocess.check_output(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', pid,
        'ip', '-br', 'addr', 'show')
    ).decode().splitlines()
    for dev_state_addrs in addr_lst:
        dev_state_addrs = dev_state_addrs.split()
        if len(dev_state_addrs) < 3:
            continue
        print(dev_state_addrs[0].split('@')[0], dev_state_addrs[2])

def sn_init_route_daemons(dir, conf_path, nodes):
    def _init_route_daemon(pid, name):
        bird_ctl_path = conf_path[:conf_path.rfind('/')] + '/bird.ctl'
        sn_container_run(pid, name, ('bird', '-c', conf_path, '-s', bird_ctl_path))

    if nodes == 'all':
        sn_operate_every_node(dir, _init_route_daemon)
    else:
        pid_map = _pid_map(f"{dir}/{PID_FILENAME}")
        nodes_lst = nodes.split(',')
        for node in nodes_lst:
            _init_route_daemon(pid_map[node], node)

def sn_ping(dir, src, dst):
    pid_map = _pid_map(f"{dir}/{PID_FILENAME}")
    # suppose src in this machine
    src_pid = pid_map[src]
    # TODO: dst in other machine
    dst_pid = pid_map[dst]
    
    dst_addr_lst = subprocess.check_output(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', dst_pid,
        'ip', '-br', 'addr', 'show')
    ).decode().splitlines()
    for dev_state_addrs in dst_addr_lst:
        dev_state_addrs = dev_state_addrs.split()
        if dev_state_addrs[0] == 'lo':
            continue
        dst_addr = dev_state_addrs[2]
        if dev_state_addrs[0].split('@')[0] == src:
            break
    dst_addr = dst_addr[:dst_addr.rfind('/')]
    print('ping', src, dst_addr)

    subprocess.run(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', src_pid,
         'ping', '-c', '4', '-i', '0.01', dst_addr),
         stdout=sys.stdout, stderr=subprocess.STDOUT
    )

def sn_iperf(dir, src, dst):
    pid_map = _pid_map(f"{dir}/{PID_FILENAME}")
    # suppose src in this machine
    src_pid = pid_map[src]
    # TODO: dst in other machine
    dst_pid = pid_map[dst]
    
    dst_addr_lst = subprocess.check_output(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', dst_pid,
        'ip', '-br', 'addr', 'show')
    ).decode().splitlines()
    for dev_state_addrs in dst_addr_lst:
        dev_state_addrs = dev_state_addrs.split()
        if dev_state_addrs[0] == 'lo':
            continue
        dst_addr = dev_state_addrs[2]
        if dev_state_addrs[0].split('@')[0] == src:
            break
    dst_addr = dst_addr[:dst_addr.rfind('/')]

    server = subprocess.Popen(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', dst_pid,
         'iperf3', '-s'),
         stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT
    )
    subprocess.run(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', src_pid,
         'iperf3', '-c', dst_addr, '-t5'),
         stdout=sys.stdout, stderr=subprocess.STDOUT
    )
    server.terminate()

def sn_sr(dir, src, dst, nxt):
    pid_map = _pid_map(f"{dir}/{PID_FILENAME}")
    # suppose src in this machine
    src_pid = pid_map[src]
    # TODO: dst in other machine
    dst_pid = pid_map[dst]

    dst_addr_lst = subprocess.check_output(
        ('nsenter', '-m', '-u', '-i', '-n', '-p', '-t', dst_pid,
        'ip', '-br', 'addr', 'show')
    ).decode().splitlines()
    for dev_state_addrs in dst_addr_lst:
        dev_state_addrs = dev_state_addrs.split()
        if dev_state_addrs[0] == 'lo':
            continue
        dst_addr = dev_state_addrs[2]
        dst_prefix = dst_addr[:dst_addr.rfind('.')] + '.0/24'
        subprocess.run(
            ('nsenter', '-n', '-t', src_pid,
            'ip', 'route', 'add', dst_prefix, 'dev', nxt),
            stdout=sys.stdout, stderr=subprocess.STDOUT
        )

def sn_check_route(dir, node):
    pid_map = _pid_map(f"{dir}/{PID_FILENAME}")
    subprocess.run(
        ('nsenter', '-n', '-t', pid_map[node],
        'route'),
        stdout=sys.stdout, stderr=subprocess.STDOUT
    )

def sn_clean(dir):
    damage_file = f"{dir}/{DAMAGE_FILENAME}"
    if os.path.exists(damage_file):
        os.remove(damage_file)
    for ns_link in glob.glob(f"/run/netns/SH*O*S*"):
        if os.path.islink(ns_link):
            os.remove(ns_link)
    for ns_link in glob.glob(f"/run/netns/G*"):
        if os.path.islink(ns_link):
            os.remove(ns_link)
    pid_file = f"{dir}/{PID_FILENAME}"
    if not os.path.exists(pid_file):
        return
    pid_map = _pid_map(pid_file, True)
    for pid in pid_map.values():
        if pid == NOT_ASSIGNED:
            continue
        try:
            os.kill(int(pid), 9)
        except ProcessLookupError:
            pass
    os.remove(pid_file)

def _change_sat_link_loss(pid, loss):
    out = subprocess.check_output(
        ('nsenter', '-t', pid, '-n',
        'tc', 'qdisc', 'show')).decode()
    for line in out.splitlines():
        line = line.strip()
        if len(line) == 0 or line.startswith('lo'):
            continue
        qdisc_netem_hd_dev_name_ = line.split()
        dev_name = qdisc_netem_hd_dev_name_[4]
        delay = qdisc_netem_hd_dev_name_[qdisc_netem_hd_dev_name_.index('delay') + 1]
        subprocess.check_call(
            ('nsenter', '-t', pid, '-n',
            'tc', 'qdisc', 'change', 'dev', dev_name, 'root',
            'netem', 'delay', delay, 'loss', loss+'%'))

def sn_damage(dir, random_list):
    with open(f"{dir}/{DAMAGE_FILENAME}", 'a') as f:
        for node in random_list:
            pid_mat = _pid_map(f"{dir}/{PID_FILENAME}")
            pid = pid_mat[node]
            out = subprocess.check_output(
                ('nsenter', '-t', pid, '-n',
                'ip', '-br', 'addr', 'show')).decode()
            dev_lst = []
            f.write(node + '|')
            for line in out.splitlines():
                line = line.strip()
                if len(line) == 0 or line.startswith('lo'):
                    continue
                toks = line.split()
                dev_name = toks[0].split('@')[0]
                for addr in toks[1:]:
                    if ':' in addr:
                        # found first ip6 addr
                        subprocess.check_call(
                            ('nsenter', '-t', pid, '-n',
                            'ip', 'link', 'set', 'dev', dev_name, 'down',))
                        dev_lst.append(f'{dev_name},{addr}')
                        break
            f.write(' '.join(dev_lst) + '\n')
            print(f'[{machine_id}] damage node: {node}')

def sn_recover(dir, sat_loss):
    damage_file = f"{dir}/{DAMAGE_FILENAME}"
    if not os.path.exists(damage_file):
        return
    
    pid_mat = _pid_map(f"{dir}/{PID_FILENAME}")
    with open(f"{dir}/{DAMAGE_FILENAME}", 'r') as f:
        for line in f:
            toks = line.strip().split('|')
            node = toks[0]

            pid = pid_mat[node]
            for link in toks[1].split():
                dev_addr = link.split(',')
                subprocess.check_call(
                    ('nsenter', '-t', pid, '-n',
                    'ip', 'link', 'set', 'dev', dev_addr[0], 'up',))
                subprocess.check_call(
                    ('nsenter', '-t', pid, '-n',
                    'ip', 'addr', 'add', 'dev', dev_addr[0], dev_addr[1]))
            print(f'[{machine_id}] recover sat: {node}')
    os.remove(damage_file)

if __name__ == '__main__':
    _pid_map_cache = None

    if len(sys.argv) < 2:
        print('Usage: sn_orchestrater.py <command> ...')
        exit(1)
    cmd = sys.argv[1]
    if cmd == 'exec':
        pid_map = _pid_map(os.path.dirname(__file__) + '/' + PID_FILENAME)
        if len(sys.argv) < 4:
            print('Usage: sn_orchestrater.py exec <node> <command> ...')
            exit(1)
        node = sys.argv[2]
        if node not in pid_map:
            print('Error:', sys.argv[3], 'not found')
            exit(1)
        # should not return
        pyctr.container_exec(
            int(pid_map[node]),
            node,
            PRELOAD_PATH,
            [arg.encode() for arg in sys.argv[3:]],
            True,
        )
        exit(-1)

    if len(sys.argv) < 3:
        machine_id = None
    else:
        try:
            machine_id = int(sys.argv[2])
        except:
            machine_id = None
    if len(sys.argv) < 4:
        workdir = os.path.dirname(__file__)
    else:
        workdir = sys.argv[3]

    damage_set = set()
    damage_file = workdir + '/' + DAMAGE_FILENAME
    if os.path.exists(damage_file):
        with open(workdir + '/' + DAMAGE_FILENAME, 'r') as f:
            for line in f:
                damage_set.add(line.strip().split(':')[0])

    shell_num, node_mid_dict, ip_lst = _get_params(workdir + '/' + ASSIGN_FILENAME)
    if cmd == 'nodes':
        sn_clean(workdir)
        sn_init_nodes(workdir, shell_num, node_mid_dict)
    elif cmd == 'list':
        print(f"{'NODE':<20} STATE")
        for name in _pid_map(workdir + '/' + PID_FILENAME):
            print(f"{name:<20} {'Damaged' if name in damage_set else 'OK'}")
    elif cmd == 'networks':
        # lp = LineProfiler()
        # sn_update_network = lp(sn_update_network)
        # lp.add_function(_update_link_intra_machine)
        sn_update_network(
            workdir, sys.argv[4], shell_num, node_mid_dict, ip_lst,
            sys.argv[5], sys.argv[6], sys.argv[7], sys.argv[8]
        )
        # with open('report.txt', 'w') as f:
            # lp.print_stats(f)
    elif cmd == 'routed':
        sn_init_route_daemons(workdir, workdir + '/bird.conf', sys.argv[4])
    elif cmd == 'IP':
        get_IP(workdir, sys.argv[4])
    elif cmd == 'damage':
        sn_damage(workdir, sys.argv[4].split(','))
    elif cmd == 'recovery':
        sn_recover(workdir, sys.argv[4])
    elif cmd == 'clean':
        sn_clean(workdir)
    elif cmd == 'ping':
        sn_ping(workdir, sys.argv[4], sys.argv[5])
    elif cmd == 'iperf':
        sn_iperf(workdir, sys.argv[4], sys.argv[5])
    elif cmd == 'sr':
        sn_sr(workdir, sys.argv[4], sys.argv[5], sys.argv[6])
    elif cmd == 'rtable':
        sn_check_route(workdir, sys.argv[4])
    else:
        print('Unknown command')
    os.close(main_net_fd)
