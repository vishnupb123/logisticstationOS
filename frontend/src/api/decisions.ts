import { api } from "./client";
import type {
  ApproveDecisionRequest,
  DecisionRecordOut,
  ObserveOutcomeRequest,
  ProposeDecisionRequest,
  RejectDecisionRequest,
} from "./types";

export const decisionsApi = {
  list: (status?: string) =>
    api.get<DecisionRecordOut[]>(`/decisions${status ? `?status=${status}` : ""}`),
  get: (id: string) => api.get<DecisionRecordOut>(`/decisions/${id}`),
  propose: (request: ProposeDecisionRequest) =>
    api.post<DecisionRecordOut>("/decisions", request),
  approve: (id: string, request: ApproveDecisionRequest) =>
    api.post<DecisionRecordOut>(`/decisions/${id}/approve`, request),
  reject: (id: string, request: RejectDecisionRequest) =>
    api.post<DecisionRecordOut>(`/decisions/${id}/reject`, request),
  observeOutcome: (id: string, request: ObserveOutcomeRequest) =>
    api.post<DecisionRecordOut>(`/decisions/${id}/observe-outcome`, request),
};
