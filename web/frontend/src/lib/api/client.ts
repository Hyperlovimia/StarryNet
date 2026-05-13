import type {
  EventRecord,
  ExperimentCreatePayload,
  ExperimentRecord,
  RunRecord,
  TaskRecord,
  TopologySnapshot
} from "../models";

// FIXME
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
const USER_ID = (import.meta.env.VITE_USER_ID as string | undefined) ?? "demo-user";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": USER_ID,
      ...(init?.headers ?? {})
    }
  });

  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = await response.text();
    }
    throw new ApiError(`Request failed with status ${response.status}`, response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export const apiClient = {
  listExperiments: () => request<ExperimentRecord[]>("/experiments"),
  createExperiment: (payload: ExperimentCreatePayload) =>
    request<ExperimentRecord>("/experiments", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  getExperiment: (experimentId: string) => request<ExperimentRecord>(`/experiments/${experimentId}`),
  listRunsForExperiment: (experimentId: string) => request<RunRecord[]>(`/experiments/${experimentId}/runs`),
  createRun: (experimentId: string) =>
    request<RunRecord>(`/experiments/${experimentId}/runs`, { method: "POST" }),
  getRun: (runId: string) => request<RunRecord>(`/runs/${runId}`),
  startRun: (runId: string) => request<RunRecord>(`/runs/${runId}/start`, { method: "POST" }),
  stopRun: (runId: string) => request<RunRecord>(`/runs/${runId}/stop`, { method: "POST" }),
  cleanupRun: (runId: string) => request<RunRecord>(`/runs/${runId}/cleanup`, { method: "POST" }),
  getTopology: (runId: string, time = 0) =>
    request<TopologySnapshot>(`/runs/${runId}/topology?time=${encodeURIComponent(String(time))}`),
  listEvents: (runId: string) => request<EventRecord[]>(`/runs/${runId}/events`),
  listTasks: (runId: string) => request<TaskRecord[]>(`/runs/${runId}/tasks`),
  getTaskOutput: (runId: string, taskId: string) =>
    request<unknown>(`/runs/${runId}/tasks/${taskId}/output`)
};
