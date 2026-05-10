import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from starrynet.sn_synchronizer import StarryNet

from .models import EventCreate, ExperimentRecord, RunRecord, RunStatus, TopologyNode
from .store import MetadataStore


class ManagedRun:
    def __init__(self, experiment: ExperimentRecord, run: RunRecord, store: MetadataStore):
        self.experiment = experiment
        self.run = run
        self.store = store
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._runtime: Optional[StarryNet] = None

    def ensure_runtime(self):
        with self._lock:
            if self._runtime is None:
                runtime_root = os.path.join(self.run.artifact_dir, "runtime")
                os.makedirs(runtime_root, exist_ok=True)
                self._runtime = StarryNet(
                    self.experiment.config_path,
                    self.experiment.gs_lat_long,
                    extra_nodes_links=self.experiment.extra_nodes_links,
                    run_id=self.run.run_id,
                    artifact_root=runtime_root,
                )
            return self._runtime

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self.store.update_run(
                self.run.run_id,
                status=RunStatus.PROVISIONING,
                error=None,
                started_at=time.time(),
                finished_at=None,
            )
            self.run = self.store.get_run(self.run.run_id)
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def _run_loop(self):
        runtime = self.ensure_runtime()
        try:
            runtime.create_nodes()
            runtime.create_links()
            if self.experiment.bird_conf_path:
                runtime.run_routing_daemon(self.experiment.bird_conf_path)
            self.store.update_run(self.run.run_id, status=RunStatus.ACTIVE)
            runtime.start_emulation()
            final_status = RunStatus.CLEANED if runtime._stop_event.is_set() else RunStatus.COMPLETED
            self.store.update_run(
                self.run.run_id,
                status=final_status,
                finished_at=time.time(),
            )
        except Exception as exc:
            current = self.store.get_run(self.run.run_id)
            if current is not None and current.status in (RunStatus.STOPPING, RunStatus.CLEANED):
                self.store.update_run(
                    self.run.run_id,
                    status=RunStatus.CLEANED,
                    finished_at=time.time(),
                )
            else:
                self.store.update_run(
                    self.run.run_id,
                    status=RunStatus.FAILED,
                    error=str(exc),
                    finished_at=time.time(),
                )

    def stop(self):
        runtime = self.ensure_runtime()
        self.store.update_run(self.run.run_id, status=RunStatus.STOPPING)
        runtime.request_stop()
        runtime.clean()
        self.store.update_run(
            self.run.run_id,
            status=RunStatus.CLEANED,
            finished_at=time.time(),
        )

    def cleanup(self):
        runtime = self.ensure_runtime()
        runtime.clean()
        self.store.update_run(
            self.run.run_id,
            status=RunStatus.CLEANED,
            finished_at=time.time(),
        )

    def schedule_event(self, event: EventCreate):
        runtime = self.ensure_runtime()
        dispatcher = {
            "check_utility": lambda: runtime.check_utility(event.time),
            "check_routing_table": lambda: runtime.check_routing_table(
                node=event.params["node"], t=event.time
            ),
            "damage": lambda: runtime.set_damage(
                damaging_ratio=event.params["damaging_ratio"], t=event.time
            ),
            "recovery": lambda: runtime.set_recovery(t=event.time),
            "static_route": lambda: runtime.set_static_route(
                src=event.params["src"],
                dst=event.params["dst"],
                next_hop=event.params["next_hop"],
                t=event.time,
            ),
            "ping": lambda: runtime.set_ping(
                src=event.params["src"],
                dst=event.params["dst"],
                t=event.time,
                extra_args=event.params.get("extra_args", []),
            ),
            "iperf": lambda: runtime.set_iperf(
                src=event.params["src"],
                dst=event.params["dst"],
                t=event.time,
                src_args=event.params.get("src_args", []),
                dst_args=event.params.get("dst_args", []),
            ),
            "exec": lambda: runtime.exec_at(
                node=event.params["node"],
                cmd=event.params["cmd"],
                t=event.time,
            ),
            "netlink": lambda: runtime.set_netlink(
                node=event.params["node"],
                nlmsg=event.params["nlmsg"],
                t=event.time,
            ),
        }
        try:
            event_id = dispatcher[event.event_type]()
        except KeyError as exc:
            raise ValueError(f"unsupported event_type: {event.event_type}") from exc
        events = runtime.list_events()
        self.store.replace_events(self.run.run_id, events)
        return runtime.get_event(event_id)

    def list_events(self):
        runtime = self.ensure_runtime()
        events = runtime.list_events()
        self.store.replace_events(self.run.run_id, events)
        return events

    def list_nodes(self, at_time: int = 0):
        runtime = self.ensure_runtime()
        nodes = []
        for name, node in sorted(runtime.nodes.items()):
            ipv4 = ipv6 = None
            if node.addr4 is not None:
                ipv4 = node.addr4.compressed
            if node.addr6 is not None:
                ipv6 = node.addr6.compressed
            nodes.append(TopologyNode(
                name=name,
                node_type=node.node_type.name.lower(),
                position=list(runtime.get_position(name, at_time) or []),
                neighbors=runtime.get_neighbors(name, at_time),
                ground_stations=runtime.get_GSes(name, at_time),
                ipv4=ipv4,
                ipv6=ipv6,
            ))
        return nodes

    def list_tasks(self, node: Optional[str] = None):
        runtime = self.ensure_runtime()
        return runtime.list_tasks(node=node)

    def get_task(self, task_id: str):
        runtime = self.ensure_runtime()
        return runtime.get_task(task_id)

    def get_task_output(self, task_id: str):
        runtime = self.ensure_runtime()
        return runtime.get_task_output(task_id)


class RuntimeManager:
    def __init__(self, store: MetadataStore):
        self.store = store
        self._runs: Dict[str, ManagedRun] = {}
        self._lock = threading.Lock()

    def get_or_create(self, experiment: ExperimentRecord, run: RunRecord):
        with self._lock:
            managed = self._runs.get(run.run_id)
            if managed is None:
                managed = ManagedRun(experiment, run, self.store)
                self._runs[run.run_id] = managed
            return managed
