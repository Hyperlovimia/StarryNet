#!/usr/bin/python3
import os
import subprocess
import json
import time
import socket
import threading
import resource
import logging
import selectors
from enum import Enum
import struct
import queue
from dataclasses import dataclass, asdict, field
from typing import Dict, Optional, Any

import paramiko
from .sn_orchestrator import OrchestratorContext

MSG_MAX_SIZE = 10 * 1024 * 1024  # 10MB

# Constants from original orchestrater
ASSIGN_FILENAME = 'assign.json'
PID_FILENAME = 'container_pid.txt'
DAMAGE_FILENAME = 'damage_list.txt'
NOT_ASSIGNED = 'NA'
VXLAN_PORT = '4789'
CLONE_NEWNET = 0x40000000

# Daemon specific constants
SOCKET_PATH = '/tmp/starrynet_orchestrater.sock'
DEFAULT_PORT = 18888

class CommandStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"

class TaskStatus(Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass
class TaskRecord:
    task_id: str
    task_type: str
    node: str
    cmd: str
    output_file: str
    status: str
    created_at: float
    scheduled_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    returncode: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class SSHServerInterface(paramiko.ServerInterface):

    def __init__(self, username=None, password=None):
        self.username = username
        self.password = password

    def check_auth_password(self, username, password):
        if (self.username and username == self.username and 
            self.password and password == self.password):
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED
    
    def check_auth_publickey(self, username, key):
        return paramiko.AUTH_FAILED
    
    def check_channel_request(self, kind, chanid):
        if kind == 'session':
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
    
    def check_channel_shell_request(self, channel):
        return True
    
    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True

class OrchestraterDaemon:
    def __init__(self, workdir=None, machine_id=0, log_level=logging.WARNING,
                 port=DEFAULT_PORT, username='starrynet', password='123456'):
        self.workdir = workdir or os.path.curdir
        self.machine_id = machine_id
        self.port = port
        self.username = username
        self.password = password
        self.socket_path = SOCKET_PATH
        self.running = False

        if not os.path.exists(self.workdir):
            os.makedirs(self.workdir)

        # Setup logging
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(self.workdir, 'orchestrater_daemon.log')),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(str(self.__class__))

        self.node_mid_dict = {}
        self.ip_lst = []
        self.task_seq = 0
        self.tasks: Dict[str, TaskRecord] = {}
        self.task_lock = threading.Lock()
        self.task_queue = queue.PriorityQueue()
        self.running_tasks = {}

        self._generate_ssh_keys()
        self.task_thread = threading.Thread(target=self._task_loop, daemon=True)
        self.task_thread.start()

        self.logger.info(f"Orchestrater daemon initialized on machine {self.machine_id}")
        self.logger.info(f"Working directory: {self.workdir}")

    def _signal_handler(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def _generate_ssh_keys(self):
        self.host_key_path = os.path.join(self.workdir, 'ssh_host_key')

        if os.path.exists(self.host_key_path):
            self.logger.info("Loading existing SSH host key...")
            with open(self.host_key_path, 'r') as f:
                self.host_key = paramiko.RSAKey.from_private_key(f)
        else:
            self.logger.info("Generating new SSH host key...")
            self.host_key = paramiko.RSAKey.generate(2048)
            with open(self.host_key_path, 'w') as f:
                self.host_key.write_private_key(f)

    def run(self):
        sel = selectors.DefaultSelector()

        self._start_unix_socket_server()
        sel.register(self.unix_socket, selectors.EVENT_READ, self._unix_socket_server_accept)

        self._start_ssh_server()
        sel.register(self.ssh_socket, selectors.EVENT_READ, self._ssh_server_accept)

        self.running = True
        self.logger.info("Orchestrater running ...")
        while self.running:
            events = sel.select()
            for key, mask in events:
                callback = key.data
                callback()
        self.stop()

    def _start_unix_socket_server(self):
        """Start Unix socket server"""
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self.unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.unix_socket.bind(self.socket_path)
        self.unix_socket.listen(5)

        self.logger.info(f"Unix socket server listening on {self.socket_path}")

    def _unix_socket_server_accept(self):
        """Unix socket server accept callback"""
        try:
            conn, addr = self.unix_socket.accept()
            # Handle each connection in a separate thread
            client_thread = threading.Thread(
                target=self._handle_client,
                args=(conn,),
                daemon=True
            )
            client_thread.start()
        except OSError as e:
            if self.running:
                self.logger.error(f"Unix socket accept error: {e}")

    def _start_ssh_server(self):
        """Start SSH server"""
        try:
            self.ssh_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.ssh_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.ssh_socket.bind(('0.0.0.0', self.port))
            self.ssh_socket.listen(100)

            self.logger.info(f"SSH server listening on port {self.port}")

        except Exception as e:
            self.logger.error(f"Failed to start SSH server: {e}")
            raise e

    def _ssh_server_accept(self):
        try:
            client, addr = self.ssh_socket.accept()
            self.logger.info(f"SSH connection from {addr[0]}:{addr[1]}")
    
            # Handle each SSH connection in a separate thread
            ssh_thread = threading.Thread(
                target=self._handle_ssh_client,
                args=(client, addr),
                daemon=True
            )
            ssh_thread.start()
        except Exception as e:
            if self.running:
                self.logger.error(f"SSH accept error: {e}")

    def _handle_ssh_client(self, client, addr):
        try:
            transport = paramiko.Transport(client)
            transport.add_server_key(self.host_key)
    
            server = SSHServerInterface(self.username, self.password)
            transport.start_server(server=server)
    
            channel = transport.accept(20)
            if channel is None:
                transport.close()
                return
    
            self.logger.info(f"SSH session established from {addr[0]}:{addr[1]}")
    
            self._handle_client(channel)
    
        except Exception as e:
            self.logger.error(f"SSH client handling error: {e}")
        finally:
            try:
                transport.close()
            except:
                pass

    def stop(self):
        self.logger.info("Stopping orchestrater daemon...")
        self.running = False

        if hasattr(self, 'unix_socket'):
            self.unix_socket.close()

        if hasattr(self, 'ssh_socket'):
            self.ssh_socket.close()

        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
    
        self.logger.info("Daemon stopped")

    def _send_message_with_length(self, conn, data):
        try:
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            length_prefix = struct.pack('!I', len(data))
            
            conn.sendall(length_prefix + data)
        except Exception as e:
            self.logger.error(f"Error sending message with length: {e}")
            raise

    def _receive_message_with_length(self, conn):
        try:
            length_data = self._recv_exact(conn, 4)
            if not length_data:
                return None
            
            message_length = struct.unpack('!I', length_data)[0]
            
            if message_length > MSG_MAX_SIZE:
                raise Exception(f"Message too large: {message_length} bytes")
            
            message_data = self._recv_exact(conn, message_length)
            if not message_data:
                return None
            
            return message_data
        except Exception as e:
            self.logger.error(f"Error receiving message with length: {e}")
            raise

    def _recv_exact(self, conn, length):
        data = bytearray()
        while len(data) < length:
            chunk = conn.recv(length - len(data))
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def _handle_client(self, conn):
        try:
            while self.running:
                message_data = self._receive_message_with_length(conn)
                if not message_data:
                    break

                try:
                    command = json.loads(message_data.decode('utf-8'))
                    response = self._process_command(command)
            
                    response_data = json.dumps(response)
                    self._send_message_with_length(conn, response_data)
            
                except json.JSONDecodeError as e:
                    error_response = {
                        "status": CommandStatus.ERROR.value,
                        "message": f"Invalid JSON: {e}"
                    }
                    self._send_message_with_length(conn, json.dumps(error_response))
                except Exception as e:
                    error_response = {
                        "status": CommandStatus.ERROR.value,
                        "message": f"Command processing error: {e}"
                    }
                    self._send_message_with_length(conn, json.dumps(error_response))
            
        except Exception as e:
            self.logger.error(f"Client connection error: {e}")
        finally:
            conn.close()        

    def _update_rlimits(self, wanted_soft=65536):
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_soft = min(hard, wanted_soft)
        if soft < new_soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            self.logger.info(f"Updated RLIMIT_NOFILE: soft={new_soft}, hard={hard}")

    def _get_context(self):
        if not hasattr(self, 'orchestrator_context'):
            self.orchestrator_context = OrchestratorContext(self.workdir)
            self.logger.info("Orchestrator context initialized")
        return self.orchestrator_context

    def _next_task_id(self):
        with self.task_lock:
            self.task_seq += 1
            return f"w{self.machine_id}-t{self.task_seq}"

    def _task_to_dict(self, task: TaskRecord):
        return asdict(task)

    def _enqueue_task(self, task_type, node, cmdline, delay=0.0, metadata=None):
        task_id = self._next_task_id()
        output_file = f'{task_id}.out'
        now = time.time()
        task = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            node=node.name,
            cmd=" ".join(cmdline),
            output_file=output_file,
            status=TaskStatus.SCHEDULED.value,
            created_at=now,
            scheduled_at=now + delay,
            metadata=metadata or {}
        )
        with self.task_lock:
            self.tasks[task_id] = task
        self.task_queue.put((
            task.scheduled_at,
            task_id,
            {
                "kind": "process",
                "node": node,
                "cmdline": tuple(cmdline),
            }
        ))
        return task

    def _enqueue_function_task(self, task_type, node_name, func, delay=0.0, metadata=None):
        task_id = self._next_task_id()
        output_file = f'{task_id}.out'
        now = time.time()
        task = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            node=node_name,
            cmd=task_type,
            output_file=output_file,
            status=TaskStatus.SCHEDULED.value,
            created_at=now,
            scheduled_at=now + delay,
            metadata=metadata or {}
        )
        with self.task_lock:
            self.tasks[task_id] = task
        self.task_queue.put((
            task.scheduled_at,
            task_id,
            {
                "kind": "function",
                "func": func,
            }
        ))
        return task

    def _task_loop(self):
        current = None
        while True:
            time.sleep(0.1)

            if current is None:
                try:
                    current = self.task_queue.get(block=False)
                except queue.Empty:
                    current = None

            now = time.time()
            while current is not None and current[0] <= now:
                _, task_id, payload = current
                task = self.tasks.get(task_id)
                if task is not None:
                    output_path = os.path.join(self.workdir, task.output_file)
                    task.status = TaskStatus.RUNNING.value
                    task.started_at = now
                    if payload["kind"] == "process":
                        node = payload["node"]
                        cmdline = payload["cmdline"]
                        fd = os.open(
                            output_path,
                            os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                        )
                        os.write(fd, f"{now}: {' '.join(cmdline)}\n".encode())
                        proc = node.run_command(cmdline, stdout=fd, stderr=subprocess.STDOUT)
                        os.close(fd)
                        self.running_tasks[proc] = task_id
                    else:
                        rc, output, err = payload["func"]()
                        with open(output_path, 'w') as f:
                            if output:
                                f.write(output)
                            if err:
                                if output:
                                    f.write("\n")
                                f.write(err)
                        task.finished_at = time.time()
                        task.returncode = rc
                        task.error = err or None
                        task.status = TaskStatus.SUCCEEDED.value if rc == 0 else TaskStatus.FAILED.value
                try:
                    current = self.task_queue.get(block=False)
                except queue.Empty:
                    current = None

            finished = []
            for proc, task_id in self.running_tasks.items():
                rc = proc.poll()
                if rc is None:
                    continue
                task = self.tasks.get(task_id)
                if task is not None:
                    task.finished_at = time.time()
                    task.returncode = rc
                    task.status = TaskStatus.SUCCEEDED.value if rc == 0 else TaskStatus.FAILED.value
                finished.append(proc)
            for proc in finished:
                self.running_tasks.pop(proc, None)

    def _process_command(self, command):
        try:
            t_begin = time.time()
            cmd_type = command.get('c')  # command
            timestamp = command.get('t', time.time())
            params = command.get('p', {})

            if cmd_type == 'config':
                result = self._handle_config(params)
            elif cmd_type == 'nodes':
                result = self._handle_nodes(params)
            elif cmd_type == 'damage':
                result = self._handle_damage(params)
            elif cmd_type == 'recovery':
                result = self._handle_recovery(params)
            elif cmd_type == 'routed':
                result = self._handle_routed(params)
            elif cmd_type == 'sr':
                result = self._handle_route_batch(params)
            elif cmd_type == 'list':
                result = self._handle_list(params)
            elif cmd_type == 'ping':
                result = self._handle_ping(params)
            elif cmd_type == 'iperf':
                result = self._handle_iperf(params)
            elif cmd_type == 'rtable':
                result = self._handle_rtable(params)
            elif cmd_type == 'utility':
                result = self._handle_utility(params)
            elif cmd_type == 'clean':
                result = self._handle_clean(params)
            elif cmd_type == 'exec':
                result = self._handle_exec(params)
            elif cmd_type == 'tasks':
                result = self._handle_tasks(params)
            elif cmd_type == 'task':
                result = self._handle_task(params)
            elif cmd_type == 'task_output':
                result = self._handle_task_output(params)
            elif cmd_type == 'update_network_batch':
                result = self._handle_update_network_batch(params)
            elif cmd_type ==  'netlink':
                result = self._handle_netlink(params)
            else:
                return {
                    "status": CommandStatus.ERROR.value,
                    "message": f"Unknown command: {cmd_type}"
                }

            t_finish = time.time()
            self.logger.info(f"Command: {cmd_type} at {timestamp}, duration: {t_finish - t_begin:.6f} seconds")

            return {
                "status": CommandStatus.SUCCESS.value,
                "result": result,
                "timestamp": timestamp
            }
    
        except Exception as e:
            self.logger.error(f"Command processing failed: {type(e).__name__} {e}", exc_info=True)
            return {
                "status": CommandStatus.ERROR.value,
                "message": str(e)
            }

    def _handle_config(self, params):
        try:
            self.node_mid_dict = params.get('node_mid_dict')
            self.ip_lst = params.get('ip_lst')    
    
            self.logger.info(f"Configuration received and loaded: "
                          f"nodes={len(self.node_mid_dict) if self.node_mid_dict else 0}")
    
            return {
                "message": "Configuration loaded successfully",
                "nodes_count": len(self.node_mid_dict) if self.node_mid_dict else 0
            }
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise Exception(f"Configuration loading failed: {e}")

    def _handle_nodes(self, params):
        try:
            context = self._get_context()

            all_node_names = sorted(self.node_mid_dict.keys())

            node_configs = {}
            for i, node_name in enumerate(all_node_names):
                if self.node_mid_dict[node_name] == self.machine_id:
                    node_configs[node_name] = i

            self._update_rlimits(len(node_configs) * 4)

            return context.init_nodes(self.workdir, node_configs)
        except Exception as e:
            raise Exception(f"Nodes initialization failed: {e}")

    def _handle_damage(self, params):
        try:
            context = self._get_context()
            random_list = params.get('nodes', [])
            context.damage(random_list)
            return {"message": "Damage applied successfully"}
        except Exception as e:
            raise Exception(f"Damage failed: {e}")

    def _handle_recovery(self, params):
        try:
            context = self._get_context()
            context.recover()
            return {"message": "Recovery completed successfully"}
        except Exception as e:
            raise Exception(f"Recovery failed: {e}")

    def _handle_routed(self, params):
        try:
            context = self._get_context()
            nodes = params.get('nodes', 'all')
            conf_text = params['conf']
            conf_path = os.path.join(self.workdir, 'bird.conf')
            with open(conf_path, 'w') as f:
                f.write(conf_text)
            context.init_route_daemons(conf_path, nodes)
            return {"message": "Routing daemon initialized successfully"}
        except Exception as e:
            raise Exception(f"Routing daemon initialization failed: {e}")

    def _handle_list(self, params):
        try:
            context = self._get_context()
            result = []
            for name in context.nodes.keys():
                result.append({
                    "name": name,
                    "state": "Damaged" if name in context.damage_dict else "OK"
                })
            return {"nodes": result}
        except Exception as e:
            raise Exception(f"List command failed: {e}")

    def _handle_ping(self, params):
        try:
            context = self._get_context()
            results = []
            for cmd in params.get('batch', []):
                src, dst = cmd[0], cmd[1]
                extra_args = cmd[2] if len(cmd) > 2 else []
                prepared = context.get_ping_command(src, dst, extra_args)
                if prepared is None:
                    results.append({
                        "src": src,
                        "dst": dst,
                        "ok": False,
                        "error": "src or dst node not found",
                    })
                    continue
                node, cmdline = prepared
                task = self._enqueue_task("ping", node, cmdline, metadata={"src": src, "dst": dst})
                results.append({
                    "src": src,
                    "dst": dst,
                    "ok": True,
                    "task_id": task.task_id,
                    "status": task.status,
                    "output_file": task.output_file,
                })
            return results
        except Exception as e:
            raise Exception(f"Ping failed: {e}")

    def _handle_iperf(self, params):
        try:
            context = self._get_context()
            results = []
            for cmd in params.get('batch', []):
                src, dst, src_args, dst_args = cmd[0], cmd[1], cmd[2], cmd[3]
                prepared = context.get_iperf_commands(src, dst, src_args, dst_args)
                if prepared is None:
                    results.append({
                        "src": src,
                        "dst": dst,
                        "ok": False,
                        "error": "src or dst node not found",
                    })
                    continue
                server_node, server_cmd = prepared[0]
                client_node, client_cmd = prepared[1]
                server_task = self._enqueue_task("iperf_server", server_node, server_cmd, metadata={"src": src, "dst": dst})
                client_task = self._enqueue_task("iperf_client", client_node, client_cmd, delay=1.0, metadata={"src": src, "dst": dst})
                results.append({
                    "src": src,
                    "dst": dst,
                    "ok": True,
                    "server_task_id": server_task.task_id,
                    "client_task_id": client_task.task_id,
                })
            return results
        except Exception as e:
            raise Exception(f"iPerf failed: {e}")

    def _handle_route_batch(self, params):
        try:
            context = self._get_context()
            routes_lst = params.get('batch', [])

            total_routes = 0

            for src, dst, next_hop in routes_lst:
                context.set_static_route(src, dst, next_hop)
                total_routes += 1

            return {
                "message": f"Batch static routes set successfully",
                "total_routes": total_routes
            }
        except Exception as e:
            raise Exception(f"Batch static route failed: {e}")

    def _handle_netlink(self, params):
        try:
            context = self._get_context()
            context.netlink(params.get('batch', []))
            return {"message": f"netlink commands submitted"}
        except Exception as e:
            raise Exception(f"netlink failed: {e}")

    def _handle_rtable(self, params):
        try:
            context = self._get_context()
            node = params.get('node')
            return context.check_route(node)
        except Exception as e:
            raise Exception(f"Routing table check failed: {e}")

    def _handle_utility(self, params):
        try:
            return subprocess.check_output(('vmstat', '-s'), text=True)
        except Exception as e:
            raise Exception(f"Utility check failed: {e}")

    def _handle_clean(self, params):
        try:
            context = self._get_context()
            context.clean()
            with self.task_lock:
                self.tasks.clear()
                self.running_tasks.clear()
                self.task_queue = queue.PriorityQueue()
            return {"message": "Clean completed successfully"}
        except Exception as e:
            raise Exception(f"Clean failed: {e}")

    def _handle_exec(self, params):
        try:
            context = self._get_context()
            results = []
            for node_name, cmd in params.get('batch', []):
                prepared = context.get_exec_command(node_name, cmd)
                if prepared is None:
                    results.append({
                        "node": node_name,
                        "cmd": cmd,
                        "ok": False,
                        "error": "node not found",
                    })
                    continue
                node, cmdline = prepared
                task = self._enqueue_task("exec", node, cmdline, metadata={"raw_cmd": cmd})
                results.append({
                    "node": node_name,
                    "cmd": cmd,
                    "ok": True,
                    "task_id": task.task_id,
                    "status": task.status,
                    "output_file": task.output_file,
                })
            return results
        except Exception as e:
            raise Exception(f"Exec failed: {e}")

    def _handle_tasks(self, params):
        task_type = params.get('type')
        status = params.get('status')
        node = params.get('node')
        with self.task_lock:
            tasks = list(self.tasks.values())
        result = []
        for task in tasks:
            if task_type and task.task_type != task_type:
                continue
            if status and task.status != status:
                continue
            if node and task.node != node:
                continue
            result.append(self._task_to_dict(task))
        result.sort(key=lambda item: item['created_at'])
        return result

    def _handle_task(self, params):
        task_id = params.get('task_id')
        if not task_id:
            raise Exception("task_id is required")
        with self.task_lock:
            task = self.tasks.get(task_id)
        if task is None:
            raise Exception(f"task not found: {task_id}")
        return self._task_to_dict(task)

    def _handle_task_output(self, params):
        task_id = params.get('task_id')
        if not task_id:
            raise Exception("task_id is required")
        with self.task_lock:
            task = self.tasks.get(task_id)
        if task is None:
            raise Exception(f"task not found: {task_id}")
        output_path = os.path.join(self.workdir, task.output_file)
        content = ""
        if os.path.exists(output_path):
            with open(output_path, 'r') as f:
                content = f.read()
        return {
            "task": self._task_to_dict(task),
            "output": content,
        }

    def _handle_update_network_batch(self, params):
        try:
            context = self._get_context()
            
            isl_bw = params.get('isl_bw', '1000')
            isl_loss = params.get('isl_loss', '0')
            del_lst = params.get('del', [])
            upd_lst = params.get('update', [])
            add_lst = params.get('add', [])

            for src, dst in del_lst:
                if self.node_mid_dict[src] == self.machine_id:
                    context.del_if(src, dst)
                elif self.node_mid_dict[dst] == self.machine_id:
                    context.del_if(dst, src)

            for src, dst, delay in upd_lst:
                if self.node_mid_dict[src] == self.machine_id:
                    context.update_if(src, dst, delay, isl_bw, isl_loss)
                if self.node_mid_dict[dst] == self.machine_id:
                    context.update_if(dst, src, delay, isl_bw, isl_loss)
            
            for link in add_lst:
                src, dst, delay = link[0], link[1], link[2]
                src_ifidx, src_addr4, src_addr6 = link[3], link[4], link[5]
                dst_ifidx, dst_addr4, dst_addr6 = link[6], link[7], link[8]
                if self.node_mid_dict[src] == self.machine_id:
                    if self.node_mid_dict[dst] == self.machine_id:
                        context.add_link_intra_machine(
                            src, dst,
                            src_ifidx, src_addr4, src_addr6,
                            dst_ifidx, dst_addr4, dst_addr6,
                            delay, isl_bw, isl_loss
                        )
                    else:
                        context.add_link_inter_machine(
                            src, dst,
                            context.ip_lst[context.node_mid_dict[dst]],
                            src_ifidx, src_addr4, src_addr6,
                            delay, isl_bw, isl_loss
                        )
                elif self.node_mid_dict[dst] == self.machine_id:
                    context.add_link_inter_machine(
                        dst, src,
                        context.ip_lst[context.node_mid_dict[dst]],
                        dst_ifidx, dst_addr4, dst_addr6,
                        delay, isl_bw, isl_loss
                    )
            return f'Delete {len(del_lst)}, update {len(upd_lst)}, add {len(add_lst)} links'

        except Exception as e:
            raise Exception(f'Network update failed: {str(e)}')
