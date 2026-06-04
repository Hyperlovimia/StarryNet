import os
import random
import shlex
import threading
import time
from time import sleep

import numpy

try:
    import paramiko
except ImportError:
    os.system("pip3 install paramiko")
    import paramiko


def _q(value):
    return shlex.quote(str(value))


def _read_matrix(file_):
    f = open(file_)
    rows = f.readlines()
    f.close()
    rows = [row.strip('\n') for row in rows]
    return [row.split(',') for row in rows]


def _clean_command_output(lines):
    return [
        line for line in lines
        if "mesg: ttyname failed" not in line
    ]


def _looks_like_interface_name(value):
    if not value:
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyz"
                  "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "0123456789_.:-")
    return all(char in allowed for char in value)


def _right_satellite(current_sat_id, current_orbit_id, orbit_num):
    if current_orbit_id == orbit_num - 1:
        return [current_sat_id, 0]
    return [current_sat_id, current_orbit_id + 1]


def _down_satellite(current_sat_id, current_orbit_id, sat_num):
    if current_sat_id == sat_num - 1:
        return [0, current_orbit_id]
    return [current_sat_id + 1, current_orbit_id]


class MultiNodeExecutor(object):
    """SSH-backed Docker executor for StarryNet physical-node PoC mode."""

    def __init__(self, manager_spec, node_specs, node_size, image):
        self.manager_spec = manager_spec
        self.node_specs = self._normalize_node_specs(node_specs, node_size,
                                                     manager_spec)
        self.node_size = node_size
        self.image = image
        self._clients = {}
        self._sftps = {}
        self._host_specs = {}
        self._node_hosts = {}
        self._node_names = {}

        for spec in [self.manager_spec] + self.node_specs:
            key = self._host_key(spec)
            self._host_specs[key] = spec
        for spec in self.node_specs:
            node_index = int(spec["node_index"])
            self._node_hosts[node_index] = self._host_key(spec)
            self._node_names[node_index] = spec.get(
                "container_name") or "ovs_container_" + str(node_index)

    def _normalize_node_specs(self, node_specs, node_size, manager_spec):
        if not node_specs:
            return []
        normalized = []
        seen = set()
        seen_containers = {}
        for raw_spec in node_specs:
            spec = dict(raw_spec)
            node_index = int(spec["node_index"])
            if node_index in seen:
                raise RuntimeError("Duplicate starrynet node_index: " +
                                   str(node_index))
            seen.add(node_index)
            spec.setdefault("host", manager_spec["host"])
            spec.setdefault("ssh_port", manager_spec.get("ssh_port", 22))
            spec.setdefault("ssh_user", manager_spec["ssh_user"])
            spec.setdefault("ssh_auth", manager_spec.get("ssh_auth", {}))
            spec.setdefault("role", "physical")
            spec.setdefault("container_name",
                            "ovs_container_" + str(node_index))
            host_key = self._host_key(spec)
            container_key = (host_key, spec["container_name"])
            if container_key in seen_containers:
                raise RuntimeError(
                    "Duplicate container_name on the same host: {0} is used "
                    "by node_index {1} and {2}".format(
                        spec["container_name"], seen_containers[container_key],
                        node_index))
            seen_containers[container_key] = node_index
            normalized.append(spec)

        expected = set(range(1, node_size + 1))
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        if missing or extra:
            raise RuntimeError(
                "starrynet_nodes must cover node indexes 1..{0}. "
                "missing={1}, extra={2}".format(node_size, missing, extra))
        return sorted(normalized, key=lambda item: int(item["node_index"]))

    def _host_key(self, spec):
        return (spec["host"], int(spec.get("ssh_port", 22)),
                spec["ssh_user"])

    def _connect(self, host_key):
        if host_key in self._clients:
            return self._clients[host_key]

        spec = self._host_specs[host_key]
        ssh_auth = spec.get("ssh_auth", {})
        if ssh_auth is None:
            ssh_auth = {}
        if isinstance(ssh_auth, str):
            ssh_auth = {"type": "password", "password": ssh_auth}
        password = (ssh_auth.get("password") or spec.get("ssh_password") or
                    spec.get("password"))
        key_filename = (ssh_auth.get("key_filename") or
                        ssh_auth.get("private_key") or
                        spec.get("ssh_key_filename"))

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = {
            "hostname": spec["host"],
            "port": int(spec.get("ssh_port", 22)),
            "username": spec["ssh_user"],
        }
        if key_filename:
            kwargs["key_filename"] = key_filename
        else:
            kwargs["password"] = password
        client.connect(**kwargs)
        self._clients[host_key] = client
        self._sftps[host_key] = paramiko.SFTPClient.from_transport(
            client.get_transport())
        return client

    def _sftp(self, host_key):
        self._connect(host_key)
        return self._sftps[host_key]

    def run_host(self, host_key, cmd, check=True):
        client = self._connect(host_key)
        stdin, stdout, stderr = client.exec_command(cmd, get_pty=True)
        out = stdout.readlines()
        err = stderr.readlines()
        code = stdout.channel.recv_exit_status()
        lines = _clean_command_output(out + err)
        if check and code != 0:
            raise RuntimeError("Command failed on {0}: {1}\n{2}".format(
                host_key[0], cmd, "".join(lines)))
        return lines

    def run_manager(self, cmd, check=True):
        return self.run_host(self._host_key(self.manager_spec), cmd, check)

    def run_node(self, node_index, cmd, check=True):
        return self.run_host(self._node_hosts[int(node_index)], cmd, check)

    def put_host(self, host_key, local_path, remote_path):
        remote_dir = os.path.dirname(remote_path)
        if remote_dir:
            self.run_host(host_key, "mkdir -p " + _q(remote_dir))
        self._sftp(host_key).put(local_path, remote_path)

    def put_node(self, node_index, local_path, remote_path):
        self.put_host(self._node_hosts[int(node_index)], local_path,
                      remote_path)

    def container_name(self, node_index):
        return self._node_names[int(node_index)]

    def docker_exec(self, node_index, command, detach=False, check=True):
        flags = "-d" if detach else "-i"
        cmd = "docker exec {0} {1} sh -lc {2}".format(
            flags, _q(self.container_name(node_index)), _q(command))
        return self.run_node(node_index, cmd, check)

    def docker_cp(self, node_index, local_path, container_path, file_path):
        remote_path = file_path + "/tmp/" + os.path.basename(local_path)
        self.put_node(node_index, local_path, remote_path)
        self.run_node(
            node_index, "docker cp {0} {1}:{2}".format(
                _q(remote_path), _q(self.container_name(node_index)),
                _q(container_path)))

    def _unique_host_keys(self):
        return sorted(set(self._node_hosts.values()))

    def prepare_workdirs(self, file_path):
        for host_key in self._unique_host_keys():
            self.run_host(host_key, "mkdir -p {0}/delay {0}/conf {0}/tmp".
                          format(_q(file_path)))

    def reset_environment(self, docker_service_name):
        print("Reset multi-node StarryNet Docker environment ...")
        manager_network_cmd = (
            "docker service rm {0} >/dev/null 2>&1 || true; "
            "for n in $(docker network ls --format '{{{{.Name}}}}' | "
            "grep -E '^(La_|Le_|GSL_|GS_)'); do "
            "docker network rm \"$n\" >/dev/null 2>&1 || true; done").format(
                _q(docker_service_name))
        self.run_manager(manager_network_cmd)

        for host_key in self._unique_host_keys():
            names = " ".join(_q(self.container_name(i))
                             for i in range(1, self.node_size + 1)
                             if self._node_hosts[i] == host_key)
            cmd = (
                "ids=$(docker ps -aq --filter label=starrynet=true); "
                "if [ -n \"$ids\" ]; then docker rm -f $ids; fi; "
                "for name in {0}; do docker rm -f \"$name\" >/dev/null 2>&1 || true; done"
            ).format(names)
            self.run_host(host_key, cmd)

    def create_nodes(self, docker_service_name):
        self.reset_environment(docker_service_name)
        for node_index in range(1, self.node_size + 1):
            name = self.container_name(node_index)
            cmd = (
                "docker run -d --name {name} --hostname {name} "
                "--label starrynet=true --label starrynet.node_index={idx} "
                "--cap-add ALL {image} ping www.baidu.com").format(
                    name=_q(name), idx=node_index, image=_q(self.image))
            self.run_node(node_index, cmd)
        return [self.container_name(index)
                for index in range(1, self.node_size + 1)]

    def create_network(self, network_name, subnet):
        cmd = (
            "docker network inspect {name} >/dev/null 2>&1 || "
            "docker network create --driver overlay --attachable "
            "--subnet {subnet} {name}").format(
                name=_q(network_name), subnet=_q(subnet))
        self.run_manager(cmd)

    def connect_network(self, node_index, network_name, ip_address):
        cmd = (
            "for i in 1 2 3 4 5; do "
            "err=$(docker network connect {network} {container} --ip {ip} 2>&1) "
            "&& exit 0; "
            "echo \"$err\" | grep -qi 'already exists' && exit 0; "
            "echo \"$err\"; sleep 1; "
            "done; exit 1").format(
                network=_q(network_name),
                container=_q(self.container_name(node_index)),
                ip=_q(ip_address))
        self.run_node(node_index, cmd)

    def disconnect_network(self, node_index, network_name):
        self.run_node(
            node_index, "docker network disconnect {0} {1} >/dev/null 2>&1 || true".
            format(_q(network_name), _q(self.container_name(node_index))))

    def remove_network(self, network_name):
        self.run_manager("docker network rm {0} >/dev/null 2>&1 || true".
                         format(_q(network_name)))

    def interface_for_ip(self, node_index, ip_address):
        for _ in range(10):
            lines = self.docker_exec(
                node_index, "ip addr | grep -B 2 {0} | head -n 1 | "
                "awk -F: '{{ print $2 }}' | tr -d '[:blank:]'".format(
                    _q(ip_address)))
            if lines:
                for line in lines:
                    interface_name = line.strip().split("@")[0]
                    if _looks_like_interface_name(interface_name):
                        return interface_name
                if lines:
                    interface_name = lines[0].strip().split("@")[0]
                if _looks_like_interface_name(interface_name):
                    return interface_name
            sleep(0.2)
        raise RuntimeError("No interface found for {0} on node {1}".format(
            ip_address, node_index))

    def configure_link_interface(self, node_index, ip_address, interface_name,
                                 delay, loss, bandwidth):
        source_interface = self.interface_for_ip(node_index, ip_address)
        self.docker_exec(
            node_index, "ip link set dev {0} down".format(
                _q(source_interface)))
        self.docker_exec(
            node_index, "ip link set dev {0} name {1}".format(
                _q(source_interface), _q(interface_name)))
        self.docker_exec(
            node_index, "ip link set dev {0} up".format(
                _q(interface_name)))
        self.docker_exec(
            node_index,
            "tc qdisc add dev {0} root netem delay {1}ms loss {2}% rate {3}Gbit".
            format(_q(interface_name), delay, loss, bandwidth))

    def configure_plain_interface(self, node_index, ip_address,
                                  interface_name):
        source_interface = self.interface_for_ip(node_index, ip_address)
        self.docker_exec(
            node_index, "ip link set dev {0} down".format(
                _q(source_interface)))
        self.docker_exec(
            node_index, "ip link set dev {0} name {1}".format(
                _q(source_interface), _q(interface_name)))
        self.docker_exec(
            node_index, "ip link set dev {0} up".format(
                _q(interface_name)))

    def establish_isl(self, current_sat_id, current_orbit_id, orbit_num,
                      sat_num, constellation_size, matrix, bw, loss,
                      created_pairs):
        current_id = current_orbit_id * sat_num + current_sat_id
        current_node = current_id + 1
        isl_idx = current_id * 2 + 1

        down_sat_id, down_orbit_id = _down_satellite(current_sat_id,
                                                     current_orbit_id,
                                                     sat_num)
        down_node = down_orbit_id * sat_num + down_sat_id + 1
        pair = tuple(sorted((current_node, down_node)))
        if current_node != down_node and pair not in created_pairs:
            network_name = "Le_{0}-{1}_{2}-{3}".format(current_sat_id,
                                                       current_orbit_id,
                                                       down_sat_id,
                                                       down_orbit_id)
            address_16_23 = isl_idx >> 8
            address_8_15 = isl_idx & 0xff
            subnet = "10.{0}.{1}.0/24".format(address_16_23, address_8_15)
            current_ip = "10.{0}.{1}.40".format(address_16_23, address_8_15)
            down_ip = "10.{0}.{1}.10".format(address_16_23, address_8_15)
            delay = matrix[current_id][down_node - 1]
            self.create_network(network_name, subnet)
            self.connect_network(current_node, network_name, current_ip)
            self.configure_link_interface(current_node, current_ip,
                                          "B{0}-eth{1}".format(
                                              current_node, down_node), delay,
                                          loss, bw)
            self.connect_network(down_node, network_name, down_ip)
            self.configure_link_interface(down_node, down_ip,
                                          "B{0}-eth{1}".format(
                                              down_node, current_node), delay,
                                          loss, bw)
            created_pairs.add(pair)

        isl_idx += 1
        right_sat_id, right_orbit_id = _right_satellite(
            current_sat_id, current_orbit_id, orbit_num)
        right_node = right_orbit_id * sat_num + right_sat_id + 1
        pair = tuple(sorted((current_node, right_node)))
        if current_node != right_node and pair not in created_pairs:
            network_name = "La_{0}-{1}_{2}-{3}".format(current_sat_id,
                                                       current_orbit_id,
                                                       right_sat_id,
                                                       right_orbit_id)
            address_16_23 = isl_idx >> 8
            address_8_15 = isl_idx & 0xff
            subnet = "10.{0}.{1}.0/24".format(address_16_23, address_8_15)
            current_ip = "10.{0}.{1}.30".format(address_16_23, address_8_15)
            right_ip = "10.{0}.{1}.20".format(address_16_23, address_8_15)
            delay = matrix[current_id][right_node - 1]
            self.create_network(network_name, subnet)
            self.connect_network(current_node, network_name, current_ip)
            self.configure_link_interface(current_node, current_ip,
                                          "B{0}-eth{1}".format(
                                              current_node, right_node), delay,
                                          loss, bw)
            self.connect_network(right_node, network_name, right_ip)
            self.configure_link_interface(right_node, right_ip,
                                          "B{0}-eth{1}".format(
                                              right_node, current_node), delay,
                                          loss, bw)
            created_pairs.add(pair)

    def establish_isls(self, matrix, orbit_num, sat_num, constellation_size, bw,
                       loss):
        created_pairs = set()
        for current_orbit_id in range(0, orbit_num):
            for current_sat_id in range(0, sat_num):
                self.establish_isl(current_sat_id, current_orbit_id,
                                   orbit_num, sat_num, constellation_size,
                                   matrix, bw, loss, created_pairs)

    def establish_gsl(self, matrix, gs_num, constellation_size, bw, loss):
        for i in range(1, constellation_size + 1):
            for j in range(constellation_size + 1,
                           constellation_size + gs_num + 1):
                if float(matrix[i - 1][j - 1]) <= 0.01:
                    continue
                self.establish_new_gsl(matrix, constellation_size, bw, loss, i,
                                       j)

        for j in range(constellation_size + 1,
                       constellation_size + gs_num + 1):
            network_name = "GS_" + str(j)
            ip_address = "9.{0}.{0}.10".format(j)
            self.create_network(network_name, "9.{0}.{0}.0/24".format(j))
            self.connect_network(j, network_name, ip_address)
            self.configure_plain_interface(j, ip_address,
                                           "B{0}-default".format(j))

    def establish_new_gsl(self, matrix, constellation_size, bw, loss,
                          sat_index, gs_index):
        delay = matrix[sat_index - 1][gs_index - 1]
        address_16_23 = (gs_index - constellation_size) & 0xff
        address_8_15 = sat_index & 0xff
        network_name = "GSL_{0}-{1}".format(sat_index, gs_index)
        subnet = "9.{0}.{1}.0/24".format(address_16_23, address_8_15)
        sat_ip = "9.{0}.{1}.50".format(address_16_23, address_8_15)
        gs_ip = "9.{0}.{1}.60".format(address_16_23, address_8_15)
        self.create_network(network_name, subnet)
        self.connect_network(sat_index, network_name, sat_ip)
        self.configure_link_interface(sat_index, sat_ip,
                                      "B{0}-eth{1}".format(
                                          sat_index, gs_index), delay, loss,
                                      bw)
        self.connect_network(gs_index, network_name, gs_ip)
        self.configure_link_interface(gs_index, gs_ip,
                                      "B{0}-eth{1}".format(
                                          gs_index, sat_index), delay, loss,
                                      bw)

    def create_links(self, delay_file, orbit_num, sat_num, constellation_size,
                     gs_num, sat_bandwidth, sat_loss, sat_ground_bandwidth,
                     sat_ground_loss):
        matrix = _read_matrix(delay_file)
        self.establish_isls(matrix, orbit_num, sat_num, constellation_size,
                            sat_bandwidth, sat_loss)
        self.establish_gsl(matrix, gs_num, constellation_size,
                           sat_ground_bandwidth, sat_ground_loss)

    def copy_run_conf_to_each_container(self, configuration_file_path,
                                        file_path, sat_node_number,
                                        fac_node_number):
        print("Copy bird configuration file to each container and run routing process."
              )
        conf_dir = "{0}/conf/bird-{1}-{2}".format(
            file_path, sat_node_number, fac_node_number)
        local_conf_dir = os.path.join(configuration_file_path, conf_dir)
        for current in range(1, self.node_size + 1):
            local_conf = os.path.join(local_conf_dir,
                                      "B{0}.conf".format(current))
            remote_conf = "{0}/B{1}.conf".format(conf_dir, current)
            self.put_node(current, local_conf, remote_conf)
            self.run_node(
                current, "docker cp {0} {1}:/B{2}.conf".format(
                    _q(remote_conf), _q(self.container_name(current)),
                    current))
            self.docker_exec(current, "bird -c B{0}.conf".format(current))
        print("Initializing routing...")
        sleep(120)
        print("Routing initialized!")

    def update_delay(self, matrix, constellation_size):
        for row in range(len(matrix)):
            for col in range(row, len(matrix[row])):
                if float(matrix[row][col]) <= 0:
                    continue
                self.delay_change(row + 1, col + 1, matrix[row][col],
                                  constellation_size)

    def delay_change(self, link_x, link_y, delay, constellation_size):
        self.docker_exec(
            link_x, "tc qdisc change dev B{0}-eth{1} root netem delay {2}ms".
            format(link_x, link_y, delay))
        self.docker_exec(
            link_y, "tc qdisc change dev B{0}-eth{1} root netem delay {2}ms".
            format(link_y, link_x, delay))

    def data_interfaces(self, node_index):
        lines = self.docker_exec(
            node_index,
            "ip -o link show | awk -F': ' '{print $2}' | "
            "cut -d@ -f1 | grep -v -E '^(lo|eth0)$' || true")
        return [line.strip() for line in lines if line.strip()]

    def damage_link(self, node_index):
        for interface_name in self.data_interfaces(node_index):
            self.docker_exec(
                node_index,
                "tc qdisc change dev {0} root netem loss 100% || "
                "tc qdisc add dev {0} root netem loss 100%".format(
                    _q(interface_name)),
                detach=True,
                check=False)

    def damage(self, ratio, damage_list, constellation_size,
               configuration_file_path, file_path):
        print("Randomly setting damaged links...\n")
        random_list = []
        while len(random_list) < int(constellation_size * ratio):
            target = int(random.uniform(0, constellation_size - 1))
            random_list.append(target)
            damage_list.append(target)
        numpy.savetxt(
            configuration_file_path + "/" + file_path +
            '/mid_files/damage_list.txt', random_list)
        for random_satellite in random_list:
            self.damage_link(int(random_satellite) + 1)
        print("Damage done.\n")

    def recover_link(self, node_index, sat_loss):
        for interface_name in self.data_interfaces(node_index):
            self.docker_exec(
                node_index,
                "tc qdisc change dev {0} root netem loss {1}% || "
                "tc qdisc add dev {0} root netem loss {1}%".format(
                    _q(interface_name), sat_loss),
                detach=True,
                check=False)

    def recover(self, damage_list, sat_loss):
        print("Recovering damaged links...\n")
        for damaged_satellite in damage_list:
            self.recover_link(int(damaged_satellite) + 1, sat_loss)
        damage_list.clear()
        print("Link recover done.\n")

    def ip_on_interface(self, node_index, interface_name):
        lines = self.docker_exec(
            node_index, "ifconfig {0} | awk -F '[ :]+' 'NR==2{{print $4}}'".
            format(_q(interface_name)))
        return lines[0].strip() if lines else ""

    def first_data_ip(self, node_index):
        interfaces = self.data_interfaces(node_index)
        if not interfaces:
            return ""
        return self.ip_on_interface(node_index, interfaces[0])

    def sr(self, src, des, target):
        des_ip = self.first_data_ip(des)
        target_ip = self.ip_on_interface(target,
                                         "B{0}-eth{1}".format(target, src))
        subnet = des_ip[:-3] + "0/24"
        self.docker_exec(src, "ip route del {0} >/dev/null 2>&1 || true".
                         format(_q(subnet)))
        self.docker_exec(
            src, "ip route add {0} dev B{1}-eth{2} via {3}".format(
                _q(subnet), src, target, _q(target_ip)))

    def ping(self, src, des, time_index, constellation_size, file_path,
             configuration_file_path):
        if des <= constellation_size:
            des_ip = self.first_data_ip(des)
        else:
            des_ip = self.ip_on_interface(des, "B{0}-default".format(des))
        result = self.docker_exec(src,
                                  "ping {0} -c 4 -i 0.01".format(_q(des_ip)))
        filename = (configuration_file_path + "/" + file_path + "/ping-" +
                    str(src) + "-" + str(des) + "_" + str(time_index) +
                    ".txt")
        f = open(filename, "w")
        f.writelines(result)
        f.close()

    def perf(self, src, des, time_index, constellation_size, file_path,
             configuration_file_path):
        if des <= constellation_size:
            des_ip = self.first_data_ip(des)
        else:
            des_ip = self.ip_on_interface(des, "B{0}-default".format(des))
        self.docker_exec(des, "iperf3 -s", detach=True)
        result = self.docker_exec(src,
                                  "iperf3 -c {0} -t 5".format(_q(des_ip)))
        filename = (configuration_file_path + "/" + file_path + "/perf-" +
                    str(src) + "-" + str(des) + "_" + str(time_index) +
                    ".txt")
        f = open(filename, "w")
        f.writelines(result)
        f.close()

    def route(self, src, time_index, file_path, configuration_file_path):
        result = self.docker_exec(src, "route")
        filename = (configuration_file_path + "/" + file_path + "/route-" +
                    str(src) + "_" + str(time_index) + ".txt")
        f = open(filename, "w")
        f.writelines(result)
        f.close()

    def check_utility(self, time_index, configuration_file_path, file_path):
        filename = (configuration_file_path + "/" + file_path +
                    "/utility-info_" + str(time_index) + ".txt")
        f = open(filename, "w")
        for host_key in self._unique_host_keys():
            f.write("### {0}\n".format(host_key[0]))
            f.writelines(self.run_host(host_key, "vmstat"))
        f.close()

    def inspect_node_ips(self, node_index):
        lines = self.run_node(
            node_index,
            "docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{\"\\n\"}}{{end}}' "
            + _q(self.container_name(node_index)))
        return [line.strip() for line in lines if line.strip()]

    def del_link(self, first_index, second_index):
        self.docker_exec(second_index,
                         "ip link set dev B{0}-eth{1} down".format(
                             second_index, first_index),
                         check=False)
        self.docker_exec(first_index,
                         "ip link set dev B{0}-eth{1} down".format(
                             first_index, second_index),
                         check=False)
        network_name = "GSL_{0}-{1}".format(first_index, second_index)
        self.disconnect_network(first_index, network_name)
        self.disconnect_network(second_index, network_name)
        self.remove_network(network_name)

    def stop_emulation(self, docker_service_name):
        print("Deleting StarryNet multi-node containers and networks...")
        self.reset_environment(docker_service_name)

    def close(self):
        for sftp in self._sftps.values():
            sftp.close()
        for client in self._clients.values():
            client.close()
        self._sftps = {}
        self._clients = {}


class MultiNodeEmulationStartThread(threading.Thread):

    def __init__(self, executor, sat_loss, sat_ground_bw, sat_ground_loss,
                 file_path, configuration_file_path, update_interval,
                 constellation_size, ping_src, ping_des, ping_time, sr_src,
                 sr_des, sr_target, sr_time, damage_ratio, damage_time,
                 damage_list, recovery_time, route_src, route_time, duration,
                 utility_checking_time, perf_src, perf_des, perf_time):
        threading.Thread.__init__(self)
        self.executor = executor
        self.sat_loss = sat_loss
        self.sat_ground_bw = sat_ground_bw
        self.sat_ground_loss = sat_ground_loss
        self.file_path = file_path
        self.configuration_file_path = configuration_file_path
        self.update_interval = update_interval
        self.constellation_size = constellation_size
        self.ping_src = ping_src
        self.ping_des = ping_des
        self.ping_time = ping_time
        self.perf_src = perf_src
        self.perf_des = perf_des
        self.perf_time = perf_time
        self.sr_src = sr_src
        self.sr_des = sr_des
        self.sr_target = sr_target
        self.sr_time = sr_time
        self.damage_ratio = damage_ratio
        self.damage_time = damage_time
        self.damage_list = damage_list
        self.recovery_time = recovery_time
        self.route_src = route_src
        self.route_time = route_time
        self.duration = duration
        self.utility_checking_time = utility_checking_time

    def _run_timed_actions(self, timeptr):
        if timeptr in self.utility_checking_time:
            self.executor.check_utility(timeptr, self.configuration_file_path,
                                        self.file_path)
        if timeptr % self.update_interval == 0:
            delay_path = (self.configuration_file_path + "/" + self.file_path +
                          '/delay/' + str(timeptr) + '.txt')
            self.executor.update_delay(_read_matrix(delay_path),
                                       self.constellation_size)
            print("Delay updating done.\n")
        if timeptr in self.damage_time:
            self.executor.damage(
                self.damage_ratio[self.damage_time.index(timeptr)],
                self.damage_list, self.constellation_size,
                self.configuration_file_path, self.file_path)
        if timeptr in self.recovery_time:
            self.executor.recover(self.damage_list, self.sat_loss)
        if timeptr in self.sr_time:
            for index_num in [
                    i for i, val in enumerate(self.sr_time) if val == timeptr
            ]:
                self.executor.sr(self.sr_src[index_num],
                                 self.sr_des[index_num],
                                 self.sr_target[index_num])
        if timeptr in self.ping_time:
            for index_num in [
                    i for i, val in enumerate(self.ping_time)
                    if val == timeptr
            ]:
                self.executor.ping(self.ping_src[index_num],
                                   self.ping_des[index_num],
                                   self.ping_time[index_num],
                                   self.constellation_size, self.file_path,
                                   self.configuration_file_path)
        if timeptr in self.perf_time:
            for index_num in [
                    i for i, val in enumerate(self.perf_time)
                    if val == timeptr
            ]:
                self.executor.perf(self.perf_src[index_num],
                                   self.perf_des[index_num],
                                   self.perf_time[index_num],
                                   self.constellation_size, self.file_path,
                                   self.configuration_file_path)
        if timeptr in self.route_time:
            for index_num in [
                    i for i, val in enumerate(self.route_time)
                    if val == timeptr
            ]:
                self.executor.route(self.route_src[index_num],
                                    self.route_time[index_num], self.file_path,
                                    self.configuration_file_path)

    def run(self):
        timeptr = 2
        topo_change_file_path = (self.configuration_file_path + "/" +
                                 self.file_path + '/Topo_leo_change.txt')
        fi = open(topo_change_file_path, 'r')
        line = fi.readline()
        while line:
            words = line.split()
            if words[0] != 'time':
                line = fi.readline()
                continue
            print('Emulation in No.' + str(timeptr) + ' second.')
            current_time = str(int(words[1][:-1]))
            while int(current_time) > timeptr:
                start_time = time.time()
                self._run_timed_actions(timeptr)
                timeptr += 1
                passed_time = min(time.time() - start_time, 1)
                sleep(1 - passed_time)
                if timeptr >= self.duration:
                    fi.close()
                    return
                print('Emulation in No.' + str(timeptr) + ' second.')

            print("A change in time " + current_time + ':')
            line = fi.readline()
            words = line.split()
            line = fi.readline()
            line = fi.readline()
            words = line.split()
            while words[0] != 'del:':
                word = words[0].split('-')
                s = int(word[0])
                f = int(word[1])
                if s > f:
                    s, f = f, s
                print("add link", s, f)
                current_topo_path = (self.configuration_file_path + "/" +
                                     self.file_path + '/delay/' +
                                     str(current_time) + '.txt')
                self.executor.establish_new_gsl(
                    _read_matrix(current_topo_path), self.constellation_size,
                    self.sat_ground_bw, self.sat_ground_loss, s, f)
                line = fi.readline()
                words = line.split()
            line = fi.readline()
            words = line.split()
            if len(words) == 0:
                fi.close()
                return
            while words[0] != 'time':
                word = words[0].split('-')
                s = int(word[0])
                f = int(word[1])
                if s > f:
                    s, f = f, s
                print("del link " + str(s) + "-" + str(f) + "\n")
                self.executor.del_link(s, f)
                line = fi.readline()
                words = line.split()
                if len(words) == 0:
                    fi.close()
                    return
            self._run_timed_actions(timeptr)
            timeptr += 1
            if timeptr >= self.duration:
                fi.close()
                return
        fi.close()


def build_multi_node_executor(sn_args, node_size):
    manager_auth = {}
    if getattr(sn_args, "remote_machine_password", None):
        manager_auth = {
            "type": "password",
            "password": sn_args.remote_machine_password
        }
    manager_spec = {
        "host": sn_args.remote_machine_IP,
        "ssh_user": sn_args.remote_machine_username,
        "ssh_port": 22,
        "ssh_auth": manager_auth,
    }
    swarm_manager = getattr(sn_args, "swarm_manager", {}) or {}
    manager_spec.update({
        key: value
        for key, value in swarm_manager.items() if value is not None
    })
    return MultiNodeExecutor(manager_spec, sn_args.starrynet_nodes, node_size,
                             sn_args.starrynet_image)
