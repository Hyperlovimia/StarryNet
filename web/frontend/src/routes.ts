export const appRoutes = {
  experiments: () => "/experiments",
  experimentCreate: () => "/experiments/new",
  experimentDetail: () => "/experiments/:experimentId",
  runDetail: () => "/runs/:runId",
  runMap: () => "/runs/:runId/map",
  runTopology: () => "/runs/:runId/topology",
  runEvents: () => "/runs/:runId/events",
  runTasks: () => "/runs/:runId/tasks",
  experimentCreatePath: () => "/experiments/new",
  experimentDetailPath: (experimentId: string) => `/experiments/${experimentId}`,
  runDetailPath: (runId: string) => `/runs/${runId}`,
  runMapPath: (runId: string) => `/runs/${runId}/map`,
  runTopologyPath: (runId: string) => `/runs/${runId}/topology`,
  runEventsPath: (runId: string) => `/runs/${runId}/events`,
  runTasksPath: (runId: string) => `/runs/${runId}/tasks`
};
