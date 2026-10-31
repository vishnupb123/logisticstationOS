import { api } from "./client";
import type { AgentExecutionDetail, AgentExecutionSummary } from "./types";

export const agentsApi = {
  listExecutions: () =>
    api.get<AgentExecutionSummary[]>("/agents/flow-intelligence/executions"),
  getExecution: (id: string) =>
    api.get<AgentExecutionDetail>(`/agents/flow-intelligence/executions/${id}`),
  run: () => api.post<AgentExecutionDetail>("/agents/flow-intelligence/run"),
};
