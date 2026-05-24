import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ErrorPanel } from "../components/ErrorPanel";
import { PageHeader } from "../components/PageHeader";
import { apiClient } from "../lib/api/client";
import type { ExperimentCreatePayload, ShellDefinition } from "../lib/models";
import { appRoutes } from "../routes";

const SATELLITE_LINK_OPTIONS = [{ value: "Grid", label: "Grid" }];
const LINK_POLICY_OPTIONS = [{ value: "LeastDelay", label: "Least delay" }];

const DEFAULT_BIRD_CONF = `log "/bird.log" { warning, error, auth, fatal, bug };
protocol device {
}
protocol direct {
    disabled;
    ipv4;
    ipv6;
}
protocol kernel {
    ipv4 {
        export all;
    };
}
protocol ospf{
    ipv4 {
        import all;
    };
    area 0 {
        interface "SH*O*S*" {
            type broadcast;
            cost 10;
            hello 5;
        };
        interface "GS*" {
            type broadcast;
            cost 10;
            hello 5;
        };
        interface "POP" {
            type broadcast;
            cost 10;
            hello 5;
        };
        interface "eth*" {
            type broadcast;
            cost 10;
            hello 5;
        };
    };
}
`;

function buildDefaultShell(): ShellDefinition {
  return {
    altitude_km: 550,
    inclination: 53,
    orbits: 5,
    satellites_per_orbit: 5,
    phase_shift: 1
  };
}

function buildDefaultPayload(): ExperimentCreatePayload {
  return {
    name: "demo-constellation",
    configuration: {
      shells: [buildDefaultShell()],
      duration_s: 120,
      step_s: 2,
      satellite_link_bandwidth_gbps: 10,
      sat_ground_bandwidth_gbps: 10,
      satellite_link_loss_percent: 1,
      sat_ground_loss_percent: 1,
      antenna_number: 1,
      antenna_elevation_angle: 25,
      satellite_link: "Grid",
      ip_version: "IPv4",
      link_policy: "LeastDelay",
      handover_policy: "instant handover"
    },
    gs_lat_long: [
      [50.110924, 8.682127],
      [46.6357, 14.311817]
    ],
    bird_routing_enabled: false,
    bird_conf_content: "",
    extra_nodes_links: {}
  };
}

function numericValue(value: string, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function CreateExperimentPage() {
  const navigate = useNavigate();
  const [payload, setPayload] = useState<ExperimentCreatePayload>(buildDefaultPayload);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateConfiguration<K extends keyof ExperimentCreatePayload["configuration"]>(
    key: K,
    value: ExperimentCreatePayload["configuration"][K]
  ) {
    setPayload(current => ({
      ...current,
      configuration: {
        ...current.configuration,
        [key]: value
      }
    }));
  }

  function updateShell(index: number, patch: Partial<ShellDefinition>) {
    setPayload(current => ({
      ...current,
      configuration: {
        ...current.configuration,
        shells: current.configuration.shells.map((shell, shellIndex) =>
          shellIndex === index ? { ...shell, ...patch } : shell
        )
      }
    }));
  }

  function addShell() {
    setPayload(current => ({
      ...current,
      configuration: {
        ...current.configuration,
        shells: [...current.configuration.shells, buildDefaultShell()]
      }
    }));
  }

  function removeShell(index: number) {
    setPayload(current => {
      if (current.configuration.shells.length === 1) {
        return current;
      }
      return {
        ...current,
        configuration: {
          ...current.configuration,
          shells: current.configuration.shells.filter((_, shellIndex) => shellIndex !== index)
        }
      };
    });
  }

  function updateGroundStation(index: number, axis: 0 | 1, value: number) {
    setPayload(current => ({
      ...current,
      gs_lat_long: current.gs_lat_long.map((station, stationIndex) =>
        stationIndex === index ? ([axis === 0 ? value : station[0], axis === 1 ? value : station[1]] as number[]) : station
      )
    }));
  }

  function addGroundStation() {
    setPayload(current => ({
      ...current,
      gs_lat_long: [...current.gs_lat_long, [0, 0]]
    }));
  }

  function removeGroundStation(index: number) {
    setPayload(current => {
      if (current.gs_lat_long.length === 1) {
        return current;
      }
      return {
        ...current,
        gs_lat_long: current.gs_lat_long.filter((_, stationIndex) => stationIndex !== index)
      };
    });
  }

  function setRoutingEnabled(enabled: boolean) {
    setPayload(current => ({
      ...current,
      bird_routing_enabled: enabled,
      bird_conf_content: enabled && !current.bird_conf_content.trim() ? DEFAULT_BIRD_CONF : current.bird_conf_content
    }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await apiClient.createExperiment(payload);
      navigate(`/experiments/${created.experiment_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create experiment");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="page-stack">
      <PageHeader
        tone="create"
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          { label: "New Experiment" }
        ]}
        title="Create Experiment"
      />

      {error ? <ErrorPanel message={error} /> : null}

      <form className="panel form-panel" onSubmit={handleSubmit}>
        <div className="form-grid">
          <label>
            <span>Name</span>
            <input
              value={payload.name}
              onChange={event => setPayload(current => ({ ...current, name: event.target.value }))}
            />
          </label>

          <label>
            <span>Duration (s)</span>
            <input
              type="number"
              min={1}
              value={payload.configuration.duration_s}
              onChange={event => updateConfiguration("duration_s", numericValue(event.target.value, 1))}
            />
          </label>

          <label>
            <span>Step (s)</span>
            <input
              type="number"
              min={1}
              value={payload.configuration.step_s}
              onChange={event => updateConfiguration("step_s", numericValue(event.target.value, 1))}
            />
          </label>

          <label>
            <span>Satellite link</span>
            <select
              value={payload.configuration.satellite_link}
              onChange={event => updateConfiguration("satellite_link", event.target.value)}
            >
              {SATELLITE_LINK_OPTIONS.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>IP version</span>
            <select value={payload.configuration.ip_version} onChange={event => updateConfiguration("ip_version", event.target.value)}>
              <option value="IPv4">IPv4</option>
              <option value="IPv6">IPv6</option>
            </select>
          </label>

          <label>
            <span>Link policy</span>
            <select
              value={payload.configuration.link_policy}
              onChange={event => updateConfiguration("link_policy", event.target.value)}
            >
              {LINK_POLICY_OPTIONS.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <section className="form-section">
          <div className="form-section-heading">
            <h3>Shells</h3>
            <button className="secondary-button" type="button" onClick={addShell}>
              Add shell
            </button>
          </div>
          <div className="form-repeat-list">
            {payload.configuration.shells.map((shell, index) => (
              <div className="form-repeat-item" key={`shell-${index}`}>
                <div className="form-repeat-heading">
                  <strong>Shell {index + 1}</strong>
                  <button
                    className="danger-inline-button"
                    type="button"
                    onClick={() => removeShell(index)}
                    disabled={payload.configuration.shells.length === 1}
                  >
                    Remove
                  </button>
                </div>
                <div className="form-grid">
                  <label>
                    <span>Altitude (km)</span>
                    <input
                      type="number"
                      min={1}
                      value={shell.altitude_km}
                      onChange={event => updateShell(index, { altitude_km: numericValue(event.target.value, 1) })}
                    />
                  </label>

                  <label>
                    <span>Inclination</span>
                    <input
                      type="number"
                      value={shell.inclination}
                      onChange={event => updateShell(index, { inclination: numericValue(event.target.value, 0) })}
                    />
                  </label>

                  <label>
                    <span>Orbits</span>
                    <input
                      type="number"
                      min={1}
                      value={shell.orbits}
                      onChange={event => updateShell(index, { orbits: numericValue(event.target.value, 1) })}
                    />
                  </label>

                  <label>
                    <span>Satellites per orbit</span>
                    <input
                      type="number"
                      min={1}
                      value={shell.satellites_per_orbit}
                      onChange={event => updateShell(index, { satellites_per_orbit: numericValue(event.target.value, 1) })}
                    />
                  </label>

                  <label>
                    <span>Phase shift</span>
                    <input
                      type="number"
                      min={0}
                      value={shell.phase_shift}
                      onChange={event => updateShell(index, { phase_shift: numericValue(event.target.value, 0) })}
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="form-section">
          <div className="form-section-heading">
            <h3>Ground stations</h3>
            <button className="secondary-button" type="button" onClick={addGroundStation}>
              Add GS
            </button>
          </div>
          <div className="form-repeat-list">
            {payload.gs_lat_long.map(([lat, lon], index) => (
              <div className="form-repeat-item" key={`gs-${index}`}>
                <div className="form-repeat-heading">
                  <strong>GS{index}</strong>
                  <button
                    className="danger-inline-button"
                    type="button"
                    onClick={() => removeGroundStation(index)}
                    disabled={payload.gs_lat_long.length === 1}
                  >
                    Remove
                  </button>
                </div>
                <div className="form-grid">
                  <label>
                    <span>Latitude</span>
                    <input
                      type="number"
                      min={-90}
                      max={90}
                      step="any"
                      value={lat}
                      onChange={event => updateGroundStation(index, 0, numericValue(event.target.value, 0))}
                    />
                  </label>

                  <label>
                    <span>Longitude</span>
                    <input
                      type="number"
                      min={-180}
                      max={180}
                      step="any"
                      value={lon}
                      onChange={event => updateGroundStation(index, 1, numericValue(event.target.value, 0))}
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="form-section">
          <label className="form-checkbox">
            <input
              type="checkbox"
              checked={payload.bird_routing_enabled}
              onChange={event => setRoutingEnabled(event.target.checked)}
            />
            <span>Enable BIRD routing</span>
          </label>

          {payload.bird_routing_enabled ? (
            <label className="form-textarea">
              <span>BIRD config content</span>
              <textarea
                rows={14}
                value={payload.bird_conf_content}
                onChange={event =>
                  setPayload(current => ({
                    ...current,
                    bird_conf_content: event.target.value
                  }))
                }
              />
            </label>
          ) : null}
        </section>

        <div className="button-row">
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? "Creating..." : "Create experiment"}
          </button>
        </div>
      </form>
    </section>
  );
}
