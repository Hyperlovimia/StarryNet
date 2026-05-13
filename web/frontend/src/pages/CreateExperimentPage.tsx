import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ErrorPanel } from "../components/ErrorPanel";
import { PageHeader } from "../components/PageHeader";
import { apiClient } from "../lib/api/client";
import type { ExperimentCreatePayload } from "../lib/models";
import { appRoutes } from "../routes";

function buildDefaultPayload(): ExperimentCreatePayload {
  return {
    name: "demo-constellation",
    configuration: {
      shells: [
        {
          altitude_km: 550,
          inclination: 53,
          orbits: 72,
          satellites_per_orbit: 22,
          phase_shift: 1
        }
      ],
      duration_s: 120,
      step_s: 2,
      satellite_link_bandwidth_gbps: 10,
      sat_ground_bandwidth_gbps: 10,
      satellite_link_loss_percent: 1,
      sat_ground_loss_percent: 1,
      antenna_number: 1,
      antenna_elevation_angle: 25,
      satellite_link: "on",
      ip_version: "ipv4",
      link_policy: "least delay",
      handover_policy: "instant handover"
    },
    gs_lat_long: [
      [50.110924, 8.682127],
      [46.6357, 14.311817]
    ],
    bird_conf_content: "",
    extra_nodes_links: {}
  };
}

export function CreateExperimentPage() {
  const navigate = useNavigate();
  const [payload, setPayload] = useState<ExperimentCreatePayload>(buildDefaultPayload);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shell = payload.configuration.shells[0];

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
        eyebrow="Create"
        tone="create"
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          { label: "New Experiment" }
        ]}
        title="Create Experiment"
        description="Create the first StarryNet experiment."
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
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    duration_s: Number(event.target.value) || 1
                  }
                }))
              }
            />
          </label>

          <label>
            <span>Step (s)</span>
            <input
              type="number"
              min={1}
              value={payload.configuration.step_s}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    step_s: Number(event.target.value) || 1
                  }
                }))
              }
            />
          </label>

          <label>
            <span>Satellite link</span>
            <input
              value={payload.configuration.satellite_link}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    satellite_link: event.target.value
                  }
                }))
              }
            />
          </label>

          <label>
            <span>IP version</span>
            <input
              value={payload.configuration.ip_version}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    ip_version: event.target.value
                  }
                }))
              }
            />
          </label>

          <label>
            <span>Link policy</span>
            <input
              value={payload.configuration.link_policy}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    link_policy: event.target.value
                  }
                }))
              }
            />
          </label>
        </div>

        <h3>Primary shell</h3>
        <div className="form-grid">
          <label>
            <span>Altitude (km)</span>
            <input
              type="number"
              min={1}
              value={shell.altitude_km}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    shells: [
                      {
                        ...current.configuration.shells[0],
                        altitude_km: Number(event.target.value) || 1
                      }
                    ]
                  }
                }))
              }
            />
          </label>

          <label>
            <span>Inclination</span>
            <input
              type="number"
              value={shell.inclination}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    shells: [
                      {
                        ...current.configuration.shells[0],
                        inclination: Number(event.target.value) || 0
                      }
                    ]
                  }
                }))
              }
            />
          </label>

          <label>
            <span>Orbits</span>
            <input
              type="number"
              min={1}
              value={shell.orbits}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    shells: [
                      {
                        ...current.configuration.shells[0],
                        orbits: Number(event.target.value) || 1
                      }
                    ]
                  }
                }))
              }
            />
          </label>

          <label>
            <span>Satellites per orbit</span>
            <input
              type="number"
              min={1}
              value={shell.satellites_per_orbit}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  configuration: {
                    ...current.configuration,
                    shells: [
                      {
                        ...current.configuration.shells[0],
                        satellites_per_orbit: Number(event.target.value) || 1
                      }
                    ]
                  }
                }))
              }
            />
          </label>
        </div>

        <h3>Ground stations</h3>
        <div className="form-grid">
          <label>
            <span>GS0 lat</span>
            <input
              type="number"
              step="any"
              value={payload.gs_lat_long[0][0]}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  gs_lat_long: [
                    [Number(event.target.value) || 0, current.gs_lat_long[0][1]],
                    current.gs_lat_long[1]
                  ]
                }))
              }
            />
          </label>

          <label>
            <span>GS0 lon</span>
            <input
              type="number"
              step="any"
              value={payload.gs_lat_long[0][1]}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  gs_lat_long: [
                    [current.gs_lat_long[0][0], Number(event.target.value) || 0],
                    current.gs_lat_long[1]
                  ]
                }))
              }
            />
          </label>

          <label>
            <span>GS1 lat</span>
            <input
              type="number"
              step="any"
              value={payload.gs_lat_long[1][0]}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  gs_lat_long: [
                    current.gs_lat_long[0],
                    [Number(event.target.value) || 0, current.gs_lat_long[1][1]]
                  ]
                }))
              }
            />
          </label>

          <label>
            <span>GS1 lon</span>
            <input
              type="number"
              step="any"
              value={payload.gs_lat_long[1][1]}
              onChange={event =>
                setPayload(current => ({
                  ...current,
                  gs_lat_long: [
                    current.gs_lat_long[0],
                    [current.gs_lat_long[1][0], Number(event.target.value) || 0]
                  ]
                }))
              }
            />
          </label>
        </div>

        <label className="form-textarea">
          <span>BIRD config content</span>
          <textarea
            rows={8}
            value={payload.bird_conf_content}
            onChange={event =>
              setPayload(current => ({
                ...current,
                bird_conf_content: event.target.value
              }))
            }
          />
        </label>

        <div className="button-row">
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? "Creating..." : "Create experiment"}
          </button>
        </div>
      </form>
    </section>
  );
}
