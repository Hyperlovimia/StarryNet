import { useState } from "react";
import { useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { PageHeader } from "../components/PageHeader";
import { SectionNav } from "../components/SectionNav";
import { apiClient } from "../lib/api/client";
import { useAsyncData } from "../lib/hooks";
import { appRoutes } from "../routes";

export function RunTasksPage() {
  const { runId = "" } = useParams();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const tasksState = useAsyncData(() => apiClient.listTasks(runId), [runId]);
  const outputState = useAsyncData(
    () => (selectedTaskId ? apiClient.getTaskOutput(runId, selectedTaskId) : Promise.resolve(null)),
    [runId, selectedTaskId]
  );

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow="Run Tasks"
        tone="tasks"
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          { label: runId, to: appRoutes.runDetailPath(runId) },
          { label: "Tasks" }
        ]}
        title="Tasks"
        description="Worker task inventory and task output preview."
      />

      <SectionNav
        title="Run Navigation"
        items={[
          { label: "Map", to: appRoutes.runMapPath(runId), description: "Geographic state" },
          { label: "Topology", to: appRoutes.runTopologyPath(runId), description: "Graph snapshot" },
          { label: "Events", to: appRoutes.runEventsPath(runId), description: "Queued runtime actions" },
          { label: "Tasks", to: appRoutes.runTasksPath(runId), description: "Current view" }
        ]}
      />

      {tasksState.loading ? <LoadingBlock /> : null}
      {tasksState.error ? <ErrorPanel message={tasksState.error.message} /> : null}

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
                        <td>{taskId}</td>
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
              {selectedTaskId ? <p className="muted-label">Task: {selectedTaskId}</p> : null}
              {outputState.loading ? <p>Loading task output...</p> : null}
              <pre className="output-panel">
                {selectedTaskId ? JSON.stringify(outputState.data, null, 2) : "Select a task to inspect output."}
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
