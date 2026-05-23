import { Link, useParams } from "react-router-dom";

import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { MetricCard } from "../components/MetricCard";
import { PageHeader } from "../components/PageHeader";
import { apiClient } from "../lib/api/client";
import { formatDateTime, formatRelativeDuration } from "../lib/format";
import { useAsyncData } from "../lib/hooks";
import { appRoutes } from "../routes";

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const runState = useAsyncData(() => apiClient.getRun(runId), [runId]);

  async function updateStatus(action: "start" | "stop" | "cleanup") {
    if (action === "start") {
      await apiClient.startRun(runId);
    } else if (action === "stop") {
      await apiClient.stopRun(runId);
    } else {
      await apiClient.cleanupRun(runId);
    }
    window.location.reload();
  }

  if (runState.loading) {
    return <LoadingBlock />;
  }

  if (runState.error || !runState.data) {
    return <ErrorPanel message={runState.error?.message ?? "Run not found"} />;
  }

  const run = runState.data;

  return (
    <section className="page-stack">
      <PageHeader
        tone="run"
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          { label: run.experiment_id, to: appRoutes.experimentDetailPath(run.experiment_id) },
          { label: run.run_id }
        ]}
        title={run.run_id}
        actions={
          <div className="button-row">
            <button className="primary-button" onClick={() => updateStatus("start")}>
              Start
            </button>
            <button className="secondary-button" onClick={() => updateStatus("stop")}>
              Stop
            </button>
            <button className="ghost-button" onClick={() => updateStatus("cleanup")}>
              Cleanup
            </button>
          </div>
        }
      />

      <section className="metric-grid">
        <MetricCard label="Status" value={run.status} />
        <MetricCard label="Started" value={formatDateTime(run.started_at)} />
        <MetricCard label="Finished" value={formatDateTime(run.finished_at)} />
        <MetricCard label="Runtime" value={formatRelativeDuration(run.started_at, run.finished_at)} />
      </section>

      <section className="destination-strip">
        <Link className="destination-item destination-map" to={appRoutes.runMapPath(run.run_id)}>
          <span className="destination-index">01</span>
          <span>
            <strong>Map</strong>
            <small>Geographic state and overlays</small>
          </span>
        </Link>
        <Link className="destination-item destination-topology" to={appRoutes.runTopologyPath(run.run_id)}>
          <span className="destination-index">02</span>
          <span>
            <strong>Topology</strong>
            <small>Graph and link snapshot</small>
          </span>
        </Link>
        <Link className="destination-item destination-events" to={appRoutes.runEventsPath(run.run_id)}>
          <span className="destination-index">03</span>
          <span>
            <strong>Events</strong>
            <small>Queued runtime actions</small>
          </span>
        </Link>
        <Link className="destination-item destination-tasks" to={appRoutes.runTasksPath(run.run_id)}>
          <span className="destination-index">04</span>
          <span>
            <strong>Tasks</strong>
            <small>Worker output</small>
          </span>
        </Link>
      </section>
    </section>
  );
}
