import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { apiClient } from "../lib/api/client";
import { formatCoordinates, formatDateTime } from "../lib/format";
import { useAsyncData } from "../lib/hooks";
import { appRoutes } from "../routes";

export function ExperimentsPage() {
  const { data, loading, error } = useAsyncData(() => apiClient.listExperiments(), []);

  return (
    <section className="page-stack">
      <PageHeader
        tone="experiments"
        title="Experiments"
        actions={
          <Link to={appRoutes.experimentCreatePath()} className="primary-link-button">
            Create experiment
          </Link>
        }
      />

      {loading ? <LoadingBlock /> : null}
      {error ? <ErrorPanel message={error.message} /> : null}

      {data ? (
        <>
          {data.length ? (
            <div className="workspace-layout">
              <aside className="summary-rail">
                <MetricCard label="Total" value={data.length} />
                <MetricCard label="Ready" value={data.filter(item => item.status === "ready").length} />
                <MetricCard label="Archived" value={data.filter(item => item.status === "archived").length} />
              </aside>
              <section className="data-section">
                <div className="section-title-row">
                  <div>
                    <h3>Experiment List</h3>
                  </div>
                </div>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Status</th>
                        <th>Shells</th>
                        <th>Duration</th>
                        <th>Ground stations</th>
                        <th>Updated</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {data.map(experiment => (
                        <tr key={experiment.experiment_id}>
                          <td>
                            <div className="table-primary-cell">
                              <strong>{experiment.name}</strong>
                            </div>
                          </td>
                          <td><StatusPill status={experiment.status} /></td>
                          <td>{experiment.configuration.shells.length}</td>
                          <td>{experiment.configuration.duration_s}s</td>
                          <td>{experiment.gs_lat_long.length}</td>
                          <td>{formatDateTime(experiment.updated_at)}</td>
                          <td>
                            <Link to={appRoutes.experimentDetailPath(experiment.experiment_id)} className="inline-link">
                              Open
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </div>
          ) : (
            <EmptyState
              title="No experiments yet"
              body="Create one here or through the backend/CLI, then this page becomes the main dashboard entry point."
            />
          )}
        </>
      ) : null}
    </section>
  );
}
