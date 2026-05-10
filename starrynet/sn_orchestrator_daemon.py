#!/usr/bin/python3
import json
import logging
import os
import queue
import resource
import selectors
import socket
import struct
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

import paramiko

from .sn_orchestrator import OrchestratorContext

MSG_MAX_SIZE = 10 * 1024 * 1024  # 10MB
DEFAULT_PORT = 18888
SOCKET_PATH = "/tmp/starrynet_orchestrater.sock"


class CommandStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"


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
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel):
        return True

    def check_channel_pty_request(
            self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True


class RunContextState:
    def __init__(self, run_id: str, base_workdir: str, machine_id: int,
                 logger: logging.Logger):
        self.run_id = run_id
        self.machine_id = machine_id
        self.logger = logger
        self.safe_run_id = self._safe_run_id(run_id)
        self.root_dir = os.path.join(base_workdir, "runs", self.safe_run_id)
        os.makedirs(self.root_dir, exist_ok=True)

        self.node_mid_dict: Dict[str, int] = {}
        self.ip_lst = []
        self.task_seq = 0
        self.tasks: Dict[str, TaskRecord] = {}
        self.task_lock = threading.Lock()
        self.task_queue = queue.PriorityQueue()
        self.running_tasks = {}
        self.stop_event = threading.Event()
        self.orchestrator_context: Optional[OrchestratorContext] = None

        self.task_thread = threading.Thread(target=self._task_loop, daemon=True)
        self.task_thread.start()

    @staticmethod
    def _safe_run_id(run_id: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in run_id)
        return safe[:48] or "default"

    def ensure_context(self):
        if self.orchestrator_context is None:
            self.orchestrator_context = OrchestratorContext(self.root_dir)
        return self.orchestrator_context

    def _next_task_id(self):
        with self.task_lock:
            self.task_seq += 1
            return f"{self.safe_run_id}-w{self.machine_id}-t{self.task_seq}"

    def task_to_dict(self, task: TaskRecord):
        return asdict(task)

    def enqueue_task(self, task_type, node, cmdline, delay=0.0, metadata=None):
        task_id = self._next_task_id()
        output_file = f"{task_id}.out"
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
            metadata=metadata or {},
        )
        with self.task_lock:
            self.tasks[task_id] = task
        self.task_queue.put((
            task.scheduled_at,
            task_id,
            {
                "node": node,
                "cmdline": tuple(cmdline),
            }
        ))
        return task

    def _task_loop(self):
        current = None
        while not self.stop_event.is_set():
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
                    output_path = os.path.join(self.root_dir, task.output_file)
                    task.status = TaskStatus.RUNNING.value
                    task.started_at = now
                    fd = os.open(
                        output_path,
                        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                    )
                    cmdline = payload["cmdline"]
                    os.write(fd, f"{now}: {' '.join(cmdline)}\n".encode())
                    proc = payload["node"].run_command(
                        cmdline, stdout=fd, stderr=subprocess.STDOUT
                    )
                    os.close(fd)
                    self.running_tasks[proc] = task_id
                try:
                    current = self.task_queue.get(block=False)
                except queue.Empty:
                    current = None

            finished = []
            for proc, task_id in list(self.running_tasks.items()):
                rc = proc.poll()
                if rc is None:
                    continue
                task = self.tasks.get(task_id)
                if task is not None:
                    task.finished_at = time.time()
                    task.returncode = rc
                    task.status = (
                        TaskStatus.SUCCEEDED.value if rc == 0
                        else TaskStatus.FAILED.value
                    )
                finished.append(proc)
            for proc in finished:
                self.running_tasks.pop(proc, None)

    def cleanup(self):
        self.stop_event.set()
        if self.orchestrator_context is not None:
            self.orchestrator_context.clean()
            self.orchestrator_context = None
        with self.task_lock:
            self.tasks.clear()
            self.running_tasks.clear()
            self.task_queue = queue.PriorityQueue()


class OrchestraterDaemon:
    def __init__(self, workdir=None, machine_id=0, log_level=logging.WARNING,
                 port=DEFAULT_PORT, username="starrynet", password="123456"):
        self.workdir = workdir or os.path.curdir
        self.machine_id = machine_id
        self.port = port
        self.username = username
        self.password = password
        self.socket_path = SOCKET_PATH
        self.running = False
        self.run_contexts: Dict[str, RunContextState] = {}
        self.run_contexts_lock = threading.Lock()

        os.makedirs(self.workdir, exist_ok=True)

        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(os.path.join(self.workdir, "orchestrater_daemon.log")),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(str(self.__class__))

        self._generate_ssh_keys()

    def _generate_ssh_keys(self):
        self.host_key_path = os.path.join(self.workdir, "ssh_host_key")

        if os.path.exists(self.host_key_path):
            with open(self.host_key_path, "r") as f:
                self.host_key = paramiko.RSAKey.from_private_key(f)
        else:
            self.host_key = paramiko.RSAKey.generate(2048)
            with open(self.host_key_path, "w") as f:
                self.host_key.write_private_key(f)

    def _safe_run_id(self, run_id: str):
        return RunContextState._safe_run_id(run_id)

    def _get_run(self, run_id: str, create: bool = True):
        safe_run_id = self._safe_run_id(run_id or "default")
        with self.run_contexts_lock:
            run_ctx = self.run_contexts.get(safe_run_id)
            if run_ctx is None and create:
                run_ctx = RunContextState(safe_run_id, self.workdir, self.machine_id, self.logger)
                self.run_contexts[safe_run_id] = run_ctx
        return run_ctx

    def _drop_run(self, run_id: str):
        safe_run_id = self._safe_run_id(run_id or "default")
        with self.run_contexts_lock:
            run_ctx = self.run_contexts.pop(safe_run_id, None)
        if run_ctx is not None:
            run_ctx.cleanup()

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
            for key, _mask in events:
                key.data()
        self.stop()

    def _start_unix_socket_server(self):
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self.unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.unix_socket.bind(self.socket_path)
        self.unix_socket.listen(5)

    def _start_ssh_server(self):
        self.ssh_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ssh_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ssh_socket.bind(("0.0.0.0", self.port))
        self.ssh_socket.listen(100)

    def _unix_socket_server_accept(self):
        try:
            conn, _addr = self.unix_socket.accept()
            threading.Thread(
                target=self._handle_client,
                args=(conn,),
                daemon=True,
            ).start()
        except OSError as exc:
            if self.running:
                self.logger.error(f"Unix socket accept error: {exc}")

    def _ssh_server_accept(self):
        try:
            client, addr = self.ssh_socket.accept()
            threading.Thread(
                target=self._handle_ssh_client,
                args=(client, addr),
                daemon=True,
            ).start()
        except Exception as exc:
            if self.running:
                self.logger.error(f"SSH accept error: {exc}")

    def _handle_ssh_client(self, client, addr):
        transport = None
        try:
            transport = paramiko.Transport(client)
            transport.add_server_key(self.host_key)
            server = SSHServerInterface(self.username, self.password)
            transport.start_server(server=server)
            channel = transport.accept(20)
            if channel is None:
                return
            self._handle_client(channel)
        except Exception as exc:
            self.logger.error(f"SSH client handling error from {addr}: {exc}")
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass

    def stop(self):
        self.running = False
        if hasattr(self, "unix_socket"):
            self.unix_socket.close()
        if hasattr(self, "ssh_socket"):
            self.ssh_socket.close()
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        for run_id in list(self.run_contexts):
            self._drop_run(run_id)

    def _send_message_with_length(self, conn, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        conn.sendall(struct.pack("!I", len(data)) + data)

    def _receive_message_with_length(self, conn):
        length_data = self._recv_exact(conn, 4)
        if not length_data:
            return None
        message_length = struct.unpack("!I", length_data)[0]
        if message_length > MSG_MAX_SIZE:
            raise Exception(f"Message too large: {message_length} bytes")
        return self._recv_exact(conn, message_length)

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
                    command = json.loads(message_data.decode("utf-8"))
                    response = self._process_command(command)
                except json.JSONDecodeError as exc:
                    response = {
                        "status": CommandStatus.ERROR.value,
                        "message": f"Invalid JSON: {exc}",
                    }
                except Exception as exc:
                    response = {
                        "status": CommandStatus.ERROR.value,
                        "message": f"Command processing error: {exc}",
                    }
                self._send_message_with_length(conn, json.dumps(response))
        finally:
            conn.close()

    def _update_rlimits(self, wanted_soft=65536):
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_soft = min(hard, wanted_soft)
        if soft < new_soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))

    def _process_command(self, command):
        t_begin = time.time()
        cmd_type = command.get("c")
        timestamp = command.get("t", time.time())
        run_id = command.get("rid", "default")
        params = command.get("p", {})

        if cmd_type == "utility":
            result = self._handle_utility(params)
        else:
            run_ctx = self._get_run(run_id)
            if cmd_type == "config":
                result = self._handle_config(run_ctx, params)
            elif cmd_type == "nodes":
                result = self._handle_nodes(run_ctx, params)
            elif cmd_type == "damage":
                result = self._handle_damage(run_ctx, params)
            elif cmd_type == "recovery":
                result = self._handle_recovery(run_ctx, params)
            elif cmd_type == "routed":
                result = self._handle_routed(run_ctx, params)
            elif cmd_type == "sr":
                result = self._handle_route_batch(run_ctx, params)
            elif cmd_type == "list":
                result = self._handle_list(run_ctx, params)
            elif cmd_type == "ping":
                result = self._handle_ping(run_ctx, params)
            elif cmd_type == "iperf":
                result = self._handle_iperf(run_ctx, params)
            elif cmd_type == "rtable":
                result = self._handle_rtable(run_ctx, params)
            elif cmd_type == "clean":
                result = self._handle_clean(run_ctx, params)
                self._drop_run(run_id)
            elif cmd_type == "exec":
                result = self._handle_exec(run_ctx, params)
            elif cmd_type == "tasks":
                result = self._handle_tasks(run_ctx, params)
            elif cmd_type == "task":
                result = self._handle_task(run_ctx, params)
            elif cmd_type == "task_output":
                result = self._handle_task_output(run_ctx, params)
            elif cmd_type == "update_network_batch":
                result = self._handle_update_network_batch(run_ctx, params)
            elif cmd_type == "netlink":
                result = self._handle_netlink(run_ctx, params)
            else:
                return {
                    "status": CommandStatus.ERROR.value,
                    "message": f"Unknown command: {cmd_type}",
                }

        self.logger.info(
            "Command: %s run=%s at %.3f duration=%.6f",
            cmd_type, run_id, timestamp, time.time() - t_begin
        )
        return {
            "status": CommandStatus.SUCCESS.value,
            "result": result,
            "timestamp": timestamp,
        }

    def _handle_config(self, run_ctx: RunContextState, params):
        run_ctx.node_mid_dict = params.get("node_mid_dict") or {}
        run_ctx.ip_lst = params.get("ip_lst") or []
        return {
            "message": "Configuration loaded successfully",
            "nodes_count": len(run_ctx.node_mid_dict),
        }

    def _handle_nodes(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        all_node_names = sorted(run_ctx.node_mid_dict.keys())
        node_configs = {}
        for i, node_name in enumerate(all_node_names):
            if run_ctx.node_mid_dict[node_name] == self.machine_id:
                node_configs[node_name] = i
        self._update_rlimits(len(node_configs) * 4)
        return context.init_nodes(run_ctx.root_dir, node_configs)

    def _handle_damage(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        context.damage(params.get("nodes", []))
        return {"message": "Damage applied successfully"}

    def _handle_recovery(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        context.recover()
        return {"message": "Recovery completed successfully"}

    def _handle_routed(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        conf_path = os.path.join(run_ctx.root_dir, "bird.conf")
        with open(conf_path, "w") as f:
            f.write(params["conf"])
        context.init_route_daemons(conf_path, params.get("nodes", "all"))
        return {"message": "Routing daemon initialized successfully"}

    def _handle_list(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        damaged = {node.name for node in context.damage_lst}
        result = []
        for name in context.nodes.keys():
            result.append({
                "name": name,
                "state": "Damaged" if name in damaged else "OK",
            })
        return {"nodes": result}

    def _handle_ping(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        results = []
        for cmd in params.get("batch", []):
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
            task = run_ctx.enqueue_task(
                "ping", node, cmdline, metadata={"src": src, "dst": dst}
            )
            results.append({
                "src": src,
                "dst": dst,
                "ok": True,
                "task_id": task.task_id,
                "status": task.status,
                "output_file": task.output_file,
            })
        return results

    def _handle_iperf(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        results = []
        for cmd in params.get("batch", []):
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
            server_task = run_ctx.enqueue_task(
                "iperf_server", server_node, server_cmd, metadata={"src": src, "dst": dst}
            )
            client_task = run_ctx.enqueue_task(
                "iperf_client", client_node, client_cmd, delay=1.0,
                metadata={"src": src, "dst": dst}
            )
            results.append({
                "src": src,
                "dst": dst,
                "ok": True,
                "server_task_id": server_task.task_id,
                "client_task_id": client_task.task_id,
            })
        return results

    def _handle_route_batch(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        total_routes = 0
        for src, dst, next_hop in params.get("batch", []):
            context.set_static_route(src, dst, next_hop)
            total_routes += 1
        return {
            "message": "Batch static routes set successfully",
            "total_routes": total_routes,
        }

    def _handle_netlink(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        context.netlink(params.get("batch", []))
        return {"message": "netlink commands submitted"}

    def _handle_rtable(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        return context.check_route(params.get("node"))

    def _handle_utility(self, params):
        return subprocess.check_output(("vmstat", "-s"), text=True)

    def _handle_clean(self, run_ctx: RunContextState, params):
        run_ctx.cleanup()
        return {"message": "Clean completed successfully"}

    def _handle_exec(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()
        results = []
        for node_name, cmd in params.get("batch", []):
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
            task = run_ctx.enqueue_task(
                "exec", node, cmdline, metadata={"raw_cmd": cmd}
            )
            results.append({
                "node": node_name,
                "cmd": cmd,
                "ok": True,
                "task_id": task.task_id,
                "status": task.status,
                "output_file": task.output_file,
            })
        return results

    def _handle_tasks(self, run_ctx: RunContextState, params):
        task_type = params.get("type")
        status = params.get("status")
        node = params.get("node")
        with run_ctx.task_lock:
            tasks = list(run_ctx.tasks.values())
        result = []
        for task in tasks:
            if task_type and task.task_type != task_type:
                continue
            if status and task.status != status:
                continue
            if node and task.node != node:
                continue
            result.append(run_ctx.task_to_dict(task))
        result.sort(key=lambda item: item["created_at"])
        return result

    def _handle_task(self, run_ctx: RunContextState, params):
        task_id = params.get("task_id")
        if not task_id:
            raise Exception("task_id is required")
        with run_ctx.task_lock:
            task = run_ctx.tasks.get(task_id)
        if task is None:
            raise Exception(f"task not found: {task_id}")
        return run_ctx.task_to_dict(task)

    def _handle_task_output(self, run_ctx: RunContextState, params):
        task_id = params.get("task_id")
        if not task_id:
            raise Exception("task_id is required")
        with run_ctx.task_lock:
            task = run_ctx.tasks.get(task_id)
        if task is None:
            raise Exception(f"task not found: {task_id}")
        output_path = os.path.join(run_ctx.root_dir, task.output_file)
        content = ""
        if os.path.exists(output_path):
            with open(output_path, "r") as f:
                content = f.read()
        return {
            "task": run_ctx.task_to_dict(task),
            "output": content,
        }

    def _handle_update_network_batch(self, run_ctx: RunContextState, params):
        context = run_ctx.ensure_context()

        isl_bw = params.get("isl_bw", "1000")
        isl_loss = params.get("isl_loss", "0")
        del_lst = params.get("del", [])
        upd_lst = params.get("update", [])
        add_lst = params.get("add", [])

        for src, dst in del_lst:
            if run_ctx.node_mid_dict[src] == self.machine_id:
                context.del_if(src, dst)
            elif run_ctx.node_mid_dict[dst] == self.machine_id:
                context.del_if(dst, src)

        for src, dst, delay in upd_lst:
            if run_ctx.node_mid_dict[src] == self.machine_id:
                context.update_if(src, dst, delay, isl_bw, isl_loss)
            if run_ctx.node_mid_dict[dst] == self.machine_id:
                context.update_if(dst, src, delay, isl_bw, isl_loss)

        for link in add_lst:
            src, dst, delay = link[0], link[1], link[2]
            src_ifidx, src_addr4, src_addr6 = link[3], link[4], link[5]
            dst_ifidx, dst_addr4, dst_addr6 = link[6], link[7], link[8]
            if run_ctx.node_mid_dict[src] == self.machine_id:
                if run_ctx.node_mid_dict[dst] == self.machine_id:
                    context.add_link_intra_machine(
                        src, dst,
                        src_ifidx, src_addr4, src_addr6,
                        dst_ifidx, dst_addr4, dst_addr6,
                        delay, isl_bw, isl_loss,
                    )
                else:
                    context.add_link_inter_machine(
                        src, dst,
                        src_ifidx,
                        run_ctx.ip_lst[run_ctx.node_mid_dict[dst]],
                        src_addr4, src_addr6,
                        delay, isl_bw, isl_loss,
                    )
            elif run_ctx.node_mid_dict[dst] == self.machine_id:
                context.add_link_inter_machine(
                    dst, src,
                    dst_ifidx,
                    run_ctx.ip_lst[run_ctx.node_mid_dict[src]],
                    dst_addr4, dst_addr6,
                    delay, isl_bw, isl_loss,
                )

        return f"Delete {len(del_lst)}, update {len(upd_lst)}, add {len(add_lst)} links"
