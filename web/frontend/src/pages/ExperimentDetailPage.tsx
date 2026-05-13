import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { apiClient } from "../lib/api/client";
import { formatDateTime } from "../lib/format";
import { useAsyncData } from "../lib/hooks";
import { appRoutes } from "../routes";

export function ExperimentDetailPage() {
  const { experimentId = "" } = useParams();
  const [creatingRun, setCreatingRun] = useState(false);

  const experimentState = useAsyncData(() => apiClient.getExperiment(experimentId), [experimentId]);
  const runsState = useAsyncData(() => apiClient.listRunsForExperiment(experimentId), [experimentId]);

  async function handleCreateRun() {
    setCreatingRun(true);
    try {
      await apiClient.createRun(experimentId);
      window.location.reload();
    } finally {
      setCreatingRun(false);
    }
  }

  if (experimentState.loading) {
    return <LoadingBlock />;
  }

  if (experimentState.error || !experimentState.data) {
    return <ErrorPanel message={experimentState.error?.message ?? "Experiment not found"} />;
  }

  const experiment = experimentState.data;
  const runs = runsState.data ?? [];

  return (
    <section className="page-stack">
      <PageHeader
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          { label: experiment.name }
        ]}
        title={experiment.name}
        actions={
          <button className="primary-button" onClick={handleCreateRun} disabled={creatingRun}>
            {creatingRun ? "Creating..." : "Create run"}
          </button>
        }
      />

      <section className="metric-grid">
        <MetricCard label="Status" value={experiment.status} />
        <MetricCard label="Runs" value={runs.length} />
        <MetricCard label="Duration" value={`${experiment.configuration.duration_s}s`} />
        <MetricCard label="Step" value={`${experiment.configuration.step_s}s`} />
      </section>

      <div className="experiment-workbench">
        <div className="experiment-top-row">
          <section className="data-section experiment-shells-section">
            <div className="section-title-row">
              <div>
                <p className="eyebrow">Constellation</p>
                <h3>Shell details</h3>
              </div>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Shell</th>
                    <th>Altitude</th>
                    <th>Inclination</th>
                    <th>Orbits</th>
                    <th>Sats/orbit</th>
                    <th>Total sats</th>
                    <th>Phase shift</th>
                  </tr>
                </thead>
                <tbody>
                  {experiment.configuration.shells.map((shell, index) => (
                    <tr key={`${shell.altitude_km}-${index}`}>
                      <td>Shell {index + 1}</td>
                      <td>{shell.altitude_km} km</td>
                      <td>{shell.inclination}</td>
                      <td>{shell.orbits}</td>
                      <td>{shell.satellites_per_orbit}</td>
                      <td>{shell.orbits * shell.satellites_per_orbit}</td>
                      <td>{shell.phase_shift}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="inspector-section">
            <div className="section-title-row">
              <div>
                <p className="eyebrow">Ground</p>
                <h3>Ground stations</h3>
              </div>
            </div>
            <div className="ground-station-list">
              {experiment.gs_lat_long.map(([lat, lon], index) => (
                <div key={`${lat}-${lon}-${index}`} className="ground-station-row">
                  <strong>GS{index}</strong>
                  <span>{lat.toFixed(6)}, {lon.toFixed(6)}</span>
                </div>
              ))}
            </div>
          </section>
        </div>

        <section className="inspector-section">
          <div className="section-title-row">
            <div>
              <p className="eyebrow">Network</p>
              <h3>Link parameters</h3>
            </div>
          </div>
          <dl className="compact-parameter-grid">
            <div>
              <dt>Satellite link</dt>
              <dd>{experiment.configuration.satellite_link}</dd>
            </div>
            <div>
              <dt>Link policy</dt>
              <dd>{experiment.configuration.link_policy}</dd>
            </div>
            <div>
              <dt>Handover policy</dt>
              <dd>{experiment.configuration.handover_policy}</dd>
            </div>
            <div>
              <dt>Satellite bandwidth</dt>
              <dd>{experiment.configuration.satellite_link_bandwidth_gbps} Gbps</dd>
            </div>
            <div>
              <dt>Sat-ground bandwidth</dt>
              <dd>{experiment.configuration.sat_ground_bandwidth_gbps} Gbps</dd>
            </div>
            <div>
              <dt>Satellite loss</dt>
              <dd>{experiment.configuration.satellite_link_loss_percent}%</dd>
            </div>
            <div>
              <dt>Sat-ground loss</dt>
              <dd>{experiment.configuration.sat_ground_loss_percent}%</dd>
            </div>
            <div>
              <dt>Antenna number</dt>
              <dd>{experiment.configuration.antenna_number}</dd>
            </div>
            <div>
              <dt>Antenna elevation</dt>
              <dd>{experiment.configuration.antenna_elevation_angle} deg</dd>
            </div>
            <div>
              <dt>Extra links</dt>
              <dd>{Object.keys(experiment.extra_nodes_links).length}</dd>
            </div>
          </dl>
        </section>
      </div>

      <section className="data-section">
        <div className="section-title-row">
          <div>
            <p className="eyebrow">Run Inventory</p>
            <h3>Associated runs</h3>
          </div>
        </div>
        {runsState.loading ? <p>Loading runs...</p> : null}
        {runsState.error ? <ErrorPanel message={runsState.error.message} /> : null}
        {runs.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Finished</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(run => (
                  <tr key={run.run_id}>
                    <td>{run.run_id}</td>
                    <td>
                      <StatusPill status={run.status} />
                    </td>
                    <td>{formatDateTime(run.started_at)}</td>
                    <td>{formatDateTime(run.finished_at)}</td>
                    <td>
                      <Link to={appRoutes.runDetailPath(run.run_id)} className="inline-link">
                        Open run
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No runs yet"
            body="Create a run to start provisioning nodes, links, routing, and runtime artifacts."
          />
        )}
      </section>
    </section>
  );
}
