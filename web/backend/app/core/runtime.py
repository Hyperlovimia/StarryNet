import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, Optional

from starrynet.sn_synchronizer import StarryNet

from .models import (
    EventCreate,
    ExperimentRecord,
    MapEntity,
    MapLink,
    MapLinkEndpoint,
    MapOverlay,
    MapSnapshot,
    MapSummary,
    RunRecord,
    RunStatus,
    TopologyLink,
    TopologyNode,
    TopologySnapshot,
)
from .store import MetadataStore


SATELLITE_NAME_RE = re.compile(r"^SH(?P<shell>\d+)O(?P<orbit>\d+)S(?P<satellite>\d+)$")


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
        return self.get_topology_snapshot(at_time).nodes

    def get_topology_snapshot(self, at_time: int = 0):
        runtime = self.ensure_runtime()
        time_index = self._resolve_time_index(runtime, at_time)
        nodes = []
        links = []
        seen_links = set()
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

            current_links = node.links_t[time_index] if time_index < len(node.links_t) else node.links_t[-1]
            for dst_name, link in current_links.items():
                dedupe_key = tuple(sorted((name, dst_name)))
                if dedupe_key in seen_links:
                    continue
                seen_links.add(dedupe_key)
                dst_node = runtime.nodes[dst_name]
                reverse_link = dst_node.links_t[time_index].get(name) if time_index < len(dst_node.links_t) else dst_node.links_t[-1].get(name)
                link_type = self._resolve_link_type(node.node_type.name.lower(), dst_node.node_type.name.lower())
                links.append(TopologyLink(
                    source=name,
                    target=dst_name,
                    link_type=link_type,
                    source_ipv4=link.addr4.compressed if link.addr4 is not None else None,
                    target_ipv4=reverse_link.addr4.compressed if reverse_link and reverse_link.addr4 is not None else None,
                    source_ipv6=link.addr6.compressed if link.addr6 is not None else None,
                    target_ipv6=reverse_link.addr6.compressed if reverse_link and reverse_link.addr6 is not None else None,
                ))
        return TopologySnapshot(run_id=self.run.run_id, time=at_time, nodes=nodes, links=links)

    def get_map_snapshot(self, at_time: int = 0):
        runtime = self.ensure_runtime()
        time_index = self._resolve_time_index(runtime, at_time)
        resolved_time = self._resolve_time(runtime, at_time)
        entities: list[MapEntity] = []
        entity_by_id: dict[str, MapEntity] = {}
        damaged_nodes = self._damaged_nodes(runtime)

        for name, node in sorted(runtime.nodes.items()):
            lla = runtime.get_lla(name, resolved_time)
            if lla is None:
                continue
            ipv4 = node.addr4.compressed if node.addr4 is not None else None
            ipv6 = node.addr6.compressed if node.addr6 is not None else None
            neighbors = runtime.get_neighbors(name, resolved_time)
            ground_stations = runtime.get_GSes(name, resolved_time)
            entity_type = self._map_entity_type(node.node_type.name.lower())
            shell, orbit, satellite = self._parse_satellite_name(name)
            entity = MapEntity(
                id=name,
                name=name,
                entity_type=entity_type,
                lat=float(lla[0]),
                lon=self._normalize_lon(float(lla[1])),
                altitude_km=float(lla[2]) if len(lla) > 2 else 0,
                status="damaged" if name in damaged_nodes else "nominal",
                neighbor_count=len(neighbors),
                connected_ground_stations=ground_stations,
                ipv4=ipv4,
                ipv6=ipv6,
                shell=shell,
                orbit=orbit,
                satellite=satellite,
            )
            entities.append(entity)
            entity_by_id[entity.id] = entity

        links = self._build_map_links(runtime, time_index, entity_by_id)
        overlays = self._build_map_overlays(runtime, entity_by_id, links, resolved_time)
        summary = MapSummary(
            satellites=sum(1 for entity in entities if entity.entity_type == "satellite"),
            ground_stations=sum(1 for entity in entities if entity.entity_type == "ground_station"),
            extra_nodes=sum(1 for entity in entities if entity.entity_type == "extra_node"),
            links=len(links),
            overlays=len(overlays),
        )
        return MapSnapshot(
            run_id=self.run.run_id,
            experiment_id=self.experiment.experiment_id,
            time=resolved_time,
            duration_s=int(runtime.duration),
            step_s=int(runtime.step),
            entities=entities,
            links=links,
            overlays=overlays,
            summary=summary,
        )

    def _build_map_links(self, runtime: StarryNet, time_index: int, entity_by_id: dict[str, MapEntity]):
        links = []
        seen_links = set()
        for name, node in sorted(runtime.nodes.items()):
            current_links = node.links_t[time_index] if time_index < len(node.links_t) else node.links_t[-1]
            for dst_name, link in current_links.items():
                dedupe_key = tuple(sorted((name, dst_name)))
                if dedupe_key in seen_links:
                    continue
                if name not in entity_by_id or dst_name not in entity_by_id:
                    continue
                seen_links.add(dedupe_key)
                dst_node = runtime.nodes[dst_name]
                reverse_links = dst_node.links_t[time_index] if time_index < len(dst_node.links_t) else dst_node.links_t[-1]
                reverse_link = reverse_links.get(name)
                source = entity_by_id[name]
                target = entity_by_id[dst_name]
                links.append(MapLink(
                    source=name,
                    target=dst_name,
                    link_type=self._resolve_link_type(
                        node.node_type.name.lower(),
                        dst_node.node_type.name.lower(),
                    ),
                    source_ipv4=link.addr4.compressed if link.addr4 is not None else None,
                    target_ipv4=reverse_link.addr4.compressed if reverse_link and reverse_link.addr4 is not None else None,
                    source_ipv6=link.addr6.compressed if link.addr6 is not None else None,
                    target_ipv6=reverse_link.addr6.compressed if reverse_link and reverse_link.addr6 is not None else None,
                    endpoints=[
                        MapLinkEndpoint(id=source.id, lat=source.lat, lon=source.lon),
                        MapLinkEndpoint(id=target.id, lat=target.lat, lon=target.lon),
                    ],
                ))
        return links

    def _build_map_overlays(self, runtime: StarryNet, entity_by_id: dict[str, MapEntity], links: list[MapLink], at_time: int):
        overlays: list[MapOverlay] = []
        for event in runtime.list_events():
            event_time = event.get("time")
            if event_time is not None and event_time > at_time:
                continue
            entity_ids = self._event_entity_ids(event, entity_by_id)
            link_ids = self._link_ids_for_entities(entity_ids, links)
            if not entity_ids and not link_ids and event.get("event_type") not in {"damage", "recovery"}:
                continue
            overlays.append(MapOverlay(
                id=event.get("event_id") or f"event-{len(overlays)}",
                overlay_type=f"event:{event.get('event_type', 'unknown')}",
                status=event.get("status", "unknown"),
                time=event_time,
                label=self._event_label(event),
                entity_ids=entity_ids,
                link_ids=link_ids,
                severity=self._event_severity(event),
                payload=event,
            ))
        task_entities = self._task_overlays(runtime, entity_by_id, links)
        overlays.extend(task_entities)
        return overlays

    def _event_entity_ids(self, event: dict, entity_by_id: dict[str, MapEntity]):
        params = event.get("params") or {}
        entity_ids = []
        for key in ("node", "src", "dst", "next_hop"):
            value = params.get(key)
            if isinstance(value, str) and value in entity_by_id and value not in entity_ids:
                entity_ids.append(value)
        result = event.get("result") or {}
        damaged = result.get("machines", {}) if isinstance(result, dict) else {}
        if isinstance(damaged, dict):
            for nodes in damaged.values():
                if isinstance(nodes, list):
                    for node in nodes:
                        if node in entity_by_id and node not in entity_ids:
                            entity_ids.append(node)
        return entity_ids

    def _task_overlays(self, runtime: StarryNet, entity_by_id: dict[str, MapEntity], links: list[MapLink]):
        overlays = []
        for task in runtime.list_tasks():
            node = task.get("node")
            if not isinstance(node, str) or node not in entity_by_id:
                continue
            task_id = task.get("task_id") or f"task-{len(overlays)}"
            status = task.get("status", "unknown")
            overlays.append(MapOverlay(
                id=str(task_id),
                overlay_type=f"task:{task.get('task_type', task.get('type', 'command'))}",
                status=status,
                label=f"Task {task_id}",
                entity_ids=[node],
                link_ids=self._link_ids_for_entities([node], links),
                severity="error" if status == "failed" else "info",
                payload=task,
            ))
        return overlays

    def _link_ids_for_entities(self, entity_ids: list[str], links: list[MapLink]):
        if len(entity_ids) < 2:
            return []
        selected = set(entity_ids)
        return [
            f"{link.source}->{link.target}"
            for link in links
            if link.source in selected and link.target in selected
        ]

    def _event_label(self, event: dict):
        event_type = event.get("event_type", "event")
        status = event.get("status", "unknown")
        return f"{event_type} ({status})"

    def _event_severity(self, event: dict):
        if event.get("status") == "failed":
            return "error"
        if event.get("event_type") == "damage":
            return "warning"
        return "info"

    def _damaged_nodes(self, runtime: StarryNet):
        total_satellites = set(getattr(runtime, "total_sat_lst", []))
        undamaged = set(getattr(runtime, "undamaged_lst", []))
        if not total_satellites:
            return set()
        return total_satellites - undamaged

    def _resolve_time(self, runtime: StarryNet, at_time: int) -> int:
        if runtime.duration <= 0:
            return 0
        return max(0, min(int(at_time), int(runtime.duration) - 1))

    def _resolve_time_index(self, runtime: StarryNet, at_time: int) -> int:
        max_steps = max((len(node.links_t) for node in runtime.nodes.values()), default=1)
        if max_steps <= 1:
            return 0
        step = max(1, int(runtime.step))
        return max(0, min(at_time // step, max_steps - 1))

    def _resolve_link_type(self, source_type: str, target_type: str) -> str:
        node_types = {source_type, target_type}
        if node_types == {"sat"}:
            return "inter-satellite"
        if node_types == {"gs", "sat"}:
            return "ground-satellite"
        if "extra" in node_types:
            return "extra"
        return "mixed"

    def _map_entity_type(self, node_type: str):
        if node_type == "sat":
            return "satellite"
        if node_type == "gs":
            return "ground_station"
        if node_type == "extra":
            return "extra_node"
        return node_type

    def _parse_satellite_name(self, name: str):
        match = SATELLITE_NAME_RE.match(name)
        if not match:
            return None, None, None
        return (
            int(match.group("shell")),
            int(match.group("orbit")),
            int(match.group("satellite")),
        )

    def _normalize_lon(self, lon: float):
        while lon > 180:
            lon -= 360
        while lon < -180:
            lon += 360
        return lon

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
