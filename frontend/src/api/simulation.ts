import { api } from "./client";
import type { RunScenarioRequest, RunScenarioResponse, ShippedScenario } from "./types";

export const simulationApi = {
  listScenarios: () => api.get<ShippedScenario[]>("/simulation/scenarios"),
  run: (request: RunScenarioRequest) =>
    api.post<RunScenarioResponse>("/simulation/run", request),
};
