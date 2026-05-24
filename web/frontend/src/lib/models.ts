export type ExperimentStatus = "draft" | "ready" | "archived";
export type RunStatus = "ready" | "provisioning" | "active" | "stopping" | "completed" | "failed" | "cleaned";

export interface ShellDefinition {
  altitude_km: number;
  inclination: number;
  orbits: number;
  satellites_per_orbit: number;
  phase_shift: number;
}

export interface ExperimentConfiguration {
  shells: ShellDefinition[];
  duration_s: number;
  step_s: number;
  satellite_link_bandwidth_gbps: number;
  sat_ground_bandwidth_gbps: number;
  satellite_link_loss_percent: number;
  sat_ground_loss_percent: number;
  antenna_number: number;
  antenna_elevation_angle: number;
  satellite_link: string;
  ip_version: string;
  link_policy: string;
  handover_policy: string;
}

export interface ExperimentRecord {
  experiment_id: string;
  owner_user_id: string;
  name: string;
  configuration: ExperimentConfiguration;
  config_path: string;
  gs_lat_long: number[][];
  bird_routing_enabled: boolean;
  bird_conf_content: string | null;
  bird_conf_path: string | null;
  extra_nodes_links: Record<string, string[]>;
  status: ExperimentStatus;
  created_at: number;
  updated_at: number;
}

export interface ExperimentCreatePayload {
  name: string;
  configuration: ExperimentConfiguration;
  gs_lat_long: number[][];
  bird_routing_enabled: boolean;
  bird_conf_content: string;
  extra_nodes_links: Record<string, string[]>;
}

export type CoreEventType =
  | "check_utility"
  | "check_routing_table"
  | "damage"
  | "recovery"
  | "static_route"
  | "ping"
  | "iperf";

export interface RunRecord {
  run_id: string;
  experiment_id: string;
  owner_user_id: string;
  status: RunStatus;
  artifact_dir: string;
  created_at: number;
  updated_at: number;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
}

export interface TopologyNode {
  name: string;
  node_type: string;
  position: number[] | null;
  neighbors: string[];
  ground_stations: string[];
  ipv4: string | null;
  ipv6: string | null;
}

export interface TopologyLink {
  source: string;
  target: string;
  link_type: string;
  source_ipv4: string | null;
  target_ipv4: string | null;
  source_ipv6: string | null;
  target_ipv6: string | null;
}

export interface TopologySnapshot {
  run_id: string;
  time: number;
  nodes: TopologyNode[];
  links: TopologyLink[];
}

export type MapEntityType = "satellite" | "ground_station" | "extra_node" | string;

export interface MapEntity {
  id: string;
  name: string;
  entity_type: MapEntityType;
  lat: number;
  lon: number;
  altitude_km: number;
  status: string;
  neighbor_count: number;
  connected_ground_stations: string[];
  ipv4: string | null;
  ipv6: string | null;
  shell: number | null;
  orbit: number | null;
  satellite: number | null;
}

export interface MapLinkEndpoint {
  id: string;
  lat: number;
  lon: number;
}

export interface MapLink {
  source: string;
  target: string;
  link_type: string;
  source_ipv4: string | null;
  target_ipv4: string | null;
  source_ipv6: string | null;
  target_ipv6: string | null;
  endpoints: MapLinkEndpoint[];
}

export interface MapOverlay {
  id: string;
  overlay_type: string;
  status: string;
  time: number | null;
  label: string;
  entity_ids: string[];
  link_ids: string[];
  severity: string;
  payload: Record<string, unknown>;
}

export interface MapSummary {
  satellites: number;
  ground_stations: number;
  extra_nodes: number;
  links: number;
  overlays: number;
}

export interface MapSnapshot {
  run_id: string;
  experiment_id: string;
  time: number;
  duration_s: number;
  step_s: number;
  entities: MapEntity[];
  links: MapLink[];
  overlays: MapOverlay[];
  summary: MapSummary;
}

export interface EventRecord {
  event_id?: string;
  time: number;
  event_type?: string;
  type?: string;
  params: Record<string, unknown>;
  status?: string;
  error?: string | null;
}

export interface EventPayload {
  time: number;
  event_type: CoreEventType;
  params: Record<string, unknown>;
}

export interface TaskRecord {
  task_id?: string;
  node?: string;
  status?: string;
  [key: string]: unknown;
}
