import { useParams } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { PageHeader } from "../components/PageHeader";
import { SectionNav } from "../components/SectionNav";
import { apiClient } from "../lib/api/client";
import { useAsyncData } from "../lib/hooks";
import { appRoutes } from "../routes";

export function RunEventsPage() {
  const { runId = "" } = useParams();
  const eventsState = useAsyncData(() => apiClient.listEvents(runId), [runId]);

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow="Run Events"
        tone="events"
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          { label: runId, to: appRoutes.runDetailPath(runId) },
          { label: "Events" }
        ]}
        title="Events"
        description="Scheduled runtime events for the selected run."
      />

      <SectionNav
        title="Run Navigation"
        items={[
          { label: "Topology", to: appRoutes.runTopologyPath(runId), description: "Graph snapshot" },
          { label: "Events", to: appRoutes.runEventsPath(runId), description: "Current view" },
          { label: "Tasks", to: appRoutes.runTasksPath(runId), description: "Worker task output" }
        ]}
      />

      {eventsState.loading ? <LoadingBlock /> : null}
      {eventsState.error ? <ErrorPanel message={eventsState.error.message} /> : null}

      {eventsState.data ? (
        eventsState.data.length ? (
          <div className="table-wrap panel">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Type</th>
                  <th>Parameters</th>
                </tr>
              </thead>
              <tbody>
                {eventsState.data.map((event, index) => (
                  <tr key={`${event.event_type}-${event.time}-${index}`}>
                    <td>{event.time}</td>
                    <td>{event.event_type}</td>
                    <td>
                      <code>{JSON.stringify(event.params)}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No scheduled events"
            body="This run does not currently have queued runtime actions."
          />
        )
      ) : null}
    </section>
  );
}
