import { api } from "./client";
import type { EvaluateRequest, EvaluateResponse } from "./types";

export const rlApi = {
  evaluate: (request: EvaluateRequest) => api.post<EvaluateResponse>("/rl/evaluate", request),
};
