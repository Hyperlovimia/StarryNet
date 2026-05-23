import { useState } from "react";
import { useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { PageHeader } from "../components/PageHeader";
import { apiClient } from "../lib/api/client";
import { useAsyncData } from "../lib/hooks";
import { appRoutes } from "../routes";

function taskOutputText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "object" && value !== null && "output" in value) {
    const output = (value as { output: unknown }).output;
    return typeof output === "string" ? output : "";
  }
  return "";
}

function displayTaskId(taskId: string, runId: string): string {
  const prefix = `${runId}-`;
  return taskId.startsWith(prefix) ? taskId.slice(prefix.length) : taskId;
}

export function RunTasksPage() {
  const { runId = "" } = useParams();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const runState = useAsyncData(() => apiClient.getRun(runId), [runId]);
  const tasksState = useAsyncData(() => apiClient.listTasks(runId), [runId]);
  const outputState = useAsyncData(
    () => (selectedTaskId ? apiClient.getTaskOutput(runId, selectedTaskId) : Promise.resolve(null)),
    [runId, selectedTaskId]
  );
  const experimentId = runState.data?.experiment_id;

  return (
    <section className="page-stack">
      <PageHeader
        tone="tasks"
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          experimentId
            ? { label: experimentId, to: appRoutes.experimentDetailPath(experimentId) }
            : { label: "Experiment" },
          { label: runId, to: appRoutes.runDetailPath(runId) },
          { label: "Tasks" }
        ]}
        title="Tasks"
        description="Inspect task output."
      />

      {tasksState.loading ? <LoadingBlock /> : null}
      {runState.loading ? <LoadingBlock /> : null}
      {tasksState.error ? <ErrorPanel message={tasksState.error.message} /> : null}
      {runState.error ? <ErrorPanel message={runState.error.message} /> : null}

      {tasksState.data ? (
        tasksState.data.length ? (
          <div className="content-grid">
            <div className="table-wrap panel">
              <table>
                <thead>
                  <tr>
                    <th>Task ID</th>
                    <th>Node</th>
                    <th>Status</th>
                    <th>Inspect</th>
                  </tr>
                </thead>
                <tbody>
                  {tasksState.data.map((task, index) => {
                    const taskId = String(task.task_id ?? `task-${index}`);
                    return (
                      <tr key={taskId}>
                        <td>{displayTaskId(taskId, runId)}</td>
                        <td>{String(task.node ?? "-")}</td>
                        <td>{String(task.status ?? "-")}</td>
                        <td>
                          <button className="inline-button" onClick={() => setSelectedTaskId(taskId)}>
                            View output
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <article className="panel">
              <h3>Task output</h3>
              {outputState.loading ? <p>Loading task output...</p> : null}
              <pre className="output-panel">
                {selectedTaskId
                  ? taskOutputText(outputState.data) || "No command output available."
                  : "Select a task to inspect output."}
              </pre>
            </article>
          </div>
        ) : (
          <EmptyState
            title="No tasks discovered"
            body="The runtime did not report any tasks for this run yet."
          />
        )
      ) : null}
    </section>
  );
}
