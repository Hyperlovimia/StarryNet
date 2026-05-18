import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { apiClient } from "../lib/api/client";
import type { ExperimentRecord } from "../lib/models";
import { formatDateTime } from "../lib/format";
import { useAsyncData } from "../lib/hooks";
import { appRoutes } from "../routes";

export function ExperimentsPage() {
  const { data, loading, error } = useAsyncData(() => apiClient.listExperiments(), []);
  const [experiments, setExperiments] = useState<ExperimentRecord[]>([]);
  const [deletingExperimentId, setDeletingExperimentId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (data) {
      setExperiments(data);
    }
  }, [data]);

  async function handleDeleteExperiment(experiment: ExperimentRecord) {
    const confirmed = window.confirm(
      `Delete experiment "${experiment.name}"? This removes the experiment record and associated run records.`
    );
    if (!confirmed) {
      return;
    }

    setDeletingExperimentId(experiment.experiment_id);
    setDeleteError(null);
    try {
      await apiClient.deleteExperiment(experiment.experiment_id);
      setExperiments(current =>
        current.filter(item => item.experiment_id !== experiment.experiment_id)
      );
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Failed to delete experiment");
    } finally {
      setDeletingExperimentId(null);
    }
  }

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
      {deleteError ? <ErrorPanel message={deleteError} /> : null}

      {data ? (
        <>
          {experiments.length ? (
            <div className="workspace-layout">
              <aside className="summary-rail">
                <MetricCard label="Total" value={experiments.length} />
                <MetricCard label="Ready" value={experiments.filter(item => item.status === "ready").length} />
                <MetricCard label="Archived" value={experiments.filter(item => item.status === "archived").length} />
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
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {experiments.map(experiment => (
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
                            <div className="table-actions">
                              <Link to={appRoutes.experimentDetailPath(experiment.experiment_id)} className="inline-link">
                                Open
                              </Link>
                              <button
                                type="button"
                                className="danger-inline-button"
                                onClick={() => handleDeleteExperiment(experiment)}
                                disabled={deletingExperimentId === experiment.experiment_id}
                              >
                                {deletingExperimentId === experiment.experiment_id ? "Deleting..." : "Delete"}
                              </button>
                            </div>
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
