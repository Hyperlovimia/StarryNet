import json
from pathlib import Path

from .models import ExperimentRecord


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_TEMPLATE = ROOT / "config.json"


def build_config_payload(experiment: ExperimentRecord):
    cfg = experiment.configuration
    with DEFAULT_CONFIG_TEMPLATE.open("r", encoding="utf-8") as fh:
        template = json.load(fh)

    template["Name"] = experiment.name
    template["Shells"] = [
        {
            "Altitude (km)": shell.altitude_km,
            "Inclination": shell.inclination,
            "Orbits": shell.orbits,
            "Satellites per orbit": shell.satellites_per_orbit,
            "Phase shift": shell.phase_shift,
        }
        for shell in cfg.shells
    ]
    template["Duration (s)"] = cfg.duration_s
    template["step (s)"] = cfg.step_s
    template['satellite link bandwidth ("X" Gbps)'] = cfg.satellite_link_bandwidth_gbps
    template['sat-ground bandwidth ("X" Gbps)'] = cfg.sat_ground_bandwidth_gbps
    template['satellite link loss ("X"% )'] = cfg.satellite_link_loss_percent
    template['sat-ground loss ("X"% )'] = cfg.sat_ground_loss_percent
    template["antenna number"] = cfg.antenna_number
    template["antenna elevation angle"] = cfg.antenna_elevation_angle
    template["Satellite link"] = cfg.satellite_link
    template["IP version"] = cfg.ip_version
    template["Link policy"] = cfg.link_policy
    template["Handover policy"] = cfg.handover_policy
    return template


def write_config_artifact(experiment: ExperimentRecord, config_path: Path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_config_payload(experiment)
    with config_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return str(config_path)


def write_bird_conf_artifact(experiment: ExperimentRecord, bird_conf_path: Path):
    bird_conf_path.parent.mkdir(parents=True, exist_ok=True)
    if experiment.bird_conf_content is None:
        return None
    with bird_conf_path.open("w", encoding="utf-8") as fh:
        fh.write(experiment.bird_conf_content)
    return str(bird_conf_path)
