from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ShellDefinition(BaseModel):
    altitude_km: float
    inclination: float
    orbits: int
    satellites_per_orbit: int
    phase_shift: int


class ExperimentConfiguration(BaseModel):
    shells: List[ShellDefinition]
    duration_s: int
    step_s: int
    satellite_link_bandwidth_gbps: int
    sat_ground_bandwidth_gbps: int
    satellite_link_loss_percent: int
    sat_ground_loss_percent: int
    antenna_number: int
    antenna_elevation_angle: int
    satellite_link: str
    ip_version: str
    link_policy: str
    handover_policy: str = "instant handover"


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    ARCHIVED = "archived"


class RunStatus(str, Enum):
    READY = "ready"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    CLEANED = "cleaned"


class CoreEventType(str, Enum):
    CHECK_UTILITY = "check_utility"
    CHECK_ROUTING_TABLE = "check_routing_table"
    DAMAGE = "damage"
    RECOVERY = "recovery"
    STATIC_ROUTE = "static_route"
    PING = "ping"
    IPERF = "iperf"


class ExperimentRecord(BaseModel):
    experiment_id: str
    owner_user_id: str
    name: str
    configuration: ExperimentConfiguration
    config_path: str
    gs_lat_long: List[List[float]]
    bird_conf_content: Optional[str] = None
    bird_conf_path: Optional[str] = None
    extra_nodes_links: Dict[str, List[str]] = Field(default_factory=dict)
    status: ExperimentStatus = ExperimentStatus.READY
    created_at: float
    updated_at: float


class RunRecord(BaseModel):
    run_id: str
    experiment_id: str
    owner_user_id: str
    status: RunStatus = RunStatus.READY
    artifact_dir: str
    created_at: float
    updated_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None


class ExperimentCreate(BaseModel):
    name: str
    configuration: ExperimentConfiguration
    gs_lat_long: List[List[float]]
    bird_conf_content: Optional[str] = None
    extra_nodes_links: Dict[str, List[str]] = Field(default_factory=dict)


class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    configuration: Optional[ExperimentConfiguration] = None
    gs_lat_long: Optional[List[List[float]]] = None
    bird_conf_content: Optional[str] = None
    extra_nodes_links: Optional[Dict[str, List[str]]] = None
    status: Optional[ExperimentStatus] = None


class RunCreate(BaseModel):
    pass


class EventCreate(BaseModel):
    time: int = Field(ge=0)
    event_type: CoreEventType
    params: Dict[str, Any] = Field(default_factory=dict)


class EventUpdate(BaseModel):
    time: int = Field(ge=0)
    event_type: CoreEventType
    params: Dict[str, Any] = Field(default_factory=dict)


class TopologyNode(BaseModel):
    name: str
    node_type: str
    position: Optional[List[float]] = None
    neighbors: List[str] = Field(default_factory=list)
    ground_stations: List[str] = Field(default_factory=list)
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None


class TopologyLink(BaseModel):
    source: str
    target: str
    link_type: str
    source_ipv4: Optional[str] = None
    target_ipv4: Optional[str] = None
    source_ipv6: Optional[str] = None
    target_ipv6: Optional[str] = None


class TopologySnapshot(BaseModel):
    run_id: str
    time: int
    nodes: List[TopologyNode] = Field(default_factory=list)
    links: List[TopologyLink] = Field(default_factory=list)


class MapEntity(BaseModel):
    id: str
    name: str
    entity_type: str
    lat: float
    lon: float
    altitude_km: float = 0
    status: str = "nominal"
    neighbor_count: int = 0
    connected_ground_stations: List[str] = Field(default_factory=list)
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None
    shell: Optional[int] = None
    orbit: Optional[int] = None
    satellite: Optional[int] = None


class MapLinkEndpoint(BaseModel):
    id: str
    lat: float
    lon: float


class MapLink(BaseModel):
    source: str
    target: str
    link_type: str
    source_ipv4: Optional[str] = None
    target_ipv4: Optional[str] = None
    source_ipv6: Optional[str] = None
    target_ipv6: Optional[str] = None
    endpoints: List[MapLinkEndpoint] = Field(default_factory=list)


class MapOverlay(BaseModel):
    id: str
    overlay_type: str
    status: str
    time: Optional[int] = None
    label: str
    entity_ids: List[str] = Field(default_factory=list)
    link_ids: List[str] = Field(default_factory=list)
    severity: str = "info"
    payload: Dict[str, Any] = Field(default_factory=dict)


class MapSummary(BaseModel):
    satellites: int = 0
    ground_stations: int = 0
    extra_nodes: int = 0
    links: int = 0
    overlays: int = 0


class MapSnapshot(BaseModel):
    run_id: str
    experiment_id: str
    time: int
    duration_s: int
    step_s: int
    entities: List[MapEntity] = Field(default_factory=list)
    links: List[MapLink] = Field(default_factory=list)
    overlays: List[MapOverlay] = Field(default_factory=list)
    summary: MapSummary = Field(default_factory=MapSummary)
