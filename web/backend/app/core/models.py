from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


SATELLITE_LINK_OPTIONS = {"Grid"}
LINK_POLICY_OPTIONS = {"LeastDelay"}


class ShellDefinition(BaseModel):
    altitude_km: float = Field(gt=0)
    inclination: float
    orbits: int = Field(gt=0)
    satellites_per_orbit: int = Field(gt=0)
    phase_shift: int = Field(ge=0)


class ExperimentConfiguration(BaseModel):
    shells: List[ShellDefinition] = Field(min_length=1)
    duration_s: int = Field(gt=0)
    step_s: int = Field(gt=0)
    satellite_link_bandwidth_gbps: int = Field(gt=0)
    sat_ground_bandwidth_gbps: int = Field(gt=0)
    satellite_link_loss_percent: int = Field(ge=0, le=100)
    sat_ground_loss_percent: int = Field(ge=0, le=100)
    antenna_number: int = Field(gt=0)
    antenna_elevation_angle: int
    satellite_link: str
    ip_version: str
    link_policy: str
    handover_policy: str = "instant handover"

    @field_validator("satellite_link")
    @classmethod
    def validate_satellite_link(cls, value: str):
        if value not in SATELLITE_LINK_OPTIONS:
            options = ", ".join(sorted(SATELLITE_LINK_OPTIONS))
            raise ValueError(f"satellite_link must be one of: {options}")
        return value

    @field_validator("link_policy")
    @classmethod
    def validate_link_policy(cls, value: str):
        if value not in LINK_POLICY_OPTIONS:
            options = ", ".join(sorted(LINK_POLICY_OPTIONS))
            raise ValueError(f"link_policy must be one of: {options}")
        return value


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
    bird_routing_enabled: bool = False
    bird_conf_content: Optional[str] = None
    bird_conf_path: Optional[str] = None
    extra_nodes_links: Dict[str, List[str]] = Field(default_factory=dict)
    status: ExperimentStatus = ExperimentStatus.READY
    created_at: float
    updated_at: float

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_routing_enabled(cls, data):
        if isinstance(data, dict) and "bird_routing_enabled" not in data and data.get("bird_conf_path"):
            return {**data, "bird_routing_enabled": True}
        return data


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
    gs_lat_long: List[List[float]] = Field(min_length=1)
    bird_routing_enabled: bool = False
    bird_conf_content: Optional[str] = None
    extra_nodes_links: Dict[str, List[str]] = Field(default_factory=dict)

    @field_validator("gs_lat_long")
    @classmethod
    def validate_gs_lat_long(cls, value: List[List[float]]):
        return _validate_gs_lat_long(value)


class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    configuration: Optional[ExperimentConfiguration] = None
    gs_lat_long: Optional[List[List[float]]] = None
    bird_routing_enabled: Optional[bool] = None
    bird_conf_content: Optional[str] = None
    extra_nodes_links: Optional[Dict[str, List[str]]] = None
    status: Optional[ExperimentStatus] = None

    @field_validator("gs_lat_long")
    @classmethod
    def validate_optional_gs_lat_long(cls, value: Optional[List[List[float]]]):
        if value is None:
            return value
        return _validate_gs_lat_long(value)


def _validate_gs_lat_long(value: List[List[float]]):
    if len(value) == 0:
        raise ValueError("at least one ground station is required")
    for index, point in enumerate(value):
        if len(point) != 2:
            raise ValueError(f"GS{index} must contain latitude and longitude")
        lat, lon = point
        if lat < -90 or lat > 90:
            raise ValueError(f"GS{index} latitude must be between -90 and 90")
        if lon < -180 or lon > 180:
            raise ValueError(f"GS{index} longitude must be between -180 and 180")
    return value


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
