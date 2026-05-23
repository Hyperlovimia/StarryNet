import { useParams } from "react-router-dom";

import { ErrorPanel } from "../components/ErrorPanel";
import { LoadingBlock } from "../components/LoadingBlock";
import { PageHeader } from "../components/PageHeader";
import { apiClient } from "../lib/api/client";
import { useAsyncData } from "../lib/hooks";
import { appRoutes } from "../routes";
import { RunEventsEditor } from "./RunEventsEditor";

export function RunEventsPage() {
  const { runId = "" } = useParams();
  const runState = useAsyncData(() => apiClient.getRun(runId), [runId]);
  const experimentState = useAsyncData(
    () => runState.data ? apiClient.getExperiment(runState.data.experiment_id) : Promise.resolve(null),
    [runState.data?.experiment_id]
  );
  const eventsState = useAsyncData(() => apiClient.listEvents(runId), [runId]);
  const experimentId = runState.data?.experiment_id;

  return (
    <section className="page-stack">
      <PageHeader
        tone="events"
        breadcrumbs={[
          { label: "Experiments", to: appRoutes.experiments() },
          experimentId
            ? { label: experimentId, to: appRoutes.experimentDetailPath(experimentId) }
            : { label: "Experiment" },
          { label: runId, to: appRoutes.runDetailPath(runId) },
          { label: "Events" }
        ]}
        title="Events"
        description="Scheduled runtime events for the selected run."
      />

      {eventsState.loading ? <LoadingBlock /> : null}
      {runState.loading || experimentState.loading ? <LoadingBlock /> : null}
      {eventsState.error ? <ErrorPanel message={eventsState.error.message} /> : null}
      {runState.error ? <ErrorPanel message={runState.error.message} /> : null}
      {experimentState.error ? <ErrorPanel message={experimentState.error.message} /> : null}

      {eventsState.data && experimentState.data ? (
        <RunEventsEditor
          runId={runId}
          events={eventsState.data}
          duration={experimentState.data.configuration.duration_s}
          onChanged={eventsState.reload}
        />
      ) : null}
    </section>
  );
}
