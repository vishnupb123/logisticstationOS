// TypeScript mirrors of backend/app/schemas/*.py and the internal
// domain models they wrap. Kept hand-written and in sync deliberately
// (no codegen) — this is a small, stable API surface
// (docs/API_REFERENCE.md); revisit with a generator if it grows.

export type EvidenceCategory =
  | "observation"
  | "calculated"
  | "inferred"
  | "hypothesis"
  | "prediction"
  | "recommendation";

export interface Finding {
  category: EvidenceCategory;
  summary: string;
  supporting_evidence: string[];
  confidence: number | null;
  alternative_explanations: string[];
}

// --- analytics -------------------------------------------------------

export interface JackpotVolumeReading {
  cumulative_diverts: number;
  cumulative_clears: number;
  currently_in_jackpot: number;
}

export interface WipsReading {
  wip_count: number;
}

export interface InductThroughputBucket {
  hour_bucket: string;
  parcels_inducted: number;
}

export interface StowThroughputBucket {
  hour_bucket: string;
  stower_code: string | null;
  parcels_stowed: number;
}

export interface ParcelDwellTimeStats {
  parcel_count: number;
  min_dwell_seconds: number | null;
  max_dwell_seconds: number | null;
  avg_dwell_seconds: number | null;
}

// --- agents ------------------------------------------------------------

export interface AgentExecutionSummary {
  id: string;
  agent_name: string;
  status: string;
  created_at: string;
  completed_at: string | null;
}

export interface FlowIntelligenceOutput {
  findings: Finding[];
  interpretation_error: string | null;
}

export interface AgentExecutionDetail extends AgentExecutionSummary {
  input: Record<string, unknown>;
  checkpoint: Record<string, unknown> | null;
  output: FlowIntelligenceOutput | null;
  error: string | null;
  retry_count: number;
}

// --- simulation ----------------------------------------------------------

export interface ShippedScenario {
  filename: string;
  name: string;
  description: string;
}

export interface RunScenarioRequest {
  scenario: string;
  seed?: number;
}

export interface RunScenarioResponse {
  run_id: string;
  scenario_name: string;
  seed: number;
  generated_at: string;
  event_count: number;
  event_type_counts: Record<string, number>;
  source_kind: string;
}

// --- rl --------------------------------------------------------------

export type PolicyName = "static_baseline" | "rule_based_baseline";

export interface EvaluateRequest {
  scenario: string;
  seeds: number[];
  policies: PolicyName[];
}

export interface EpisodeResult {
  seed: number;
  total_reward: number;
  total_stowed: number;
  max_jackpot_backlog: number;
  constraint_violations: number;
  steps: number;
  mean_occupancy: number;
  terminated_cleanly: boolean;
}

export interface PolicyEvaluation {
  episodes: EpisodeResult[];
  aggregate: Record<string, number>;
}

export interface EvaluateResponse {
  scenario: string;
  seeds: number[];
  results: Record<string, PolicyEvaluation>;
  source_kind: string;
}

// --- decisions -----------------------------------------------------------

export type Role = "operator" | "supervisor" | "admin";

export interface CandidateIntervention {
  name: string;
  description: string;
  priority_weights: Record<string, number>;
}

export interface CandidateRecord extends CandidateIntervention {
  evaluation: PolicyEvaluation;
}

export interface PolicyEngineResult {
  eligible: boolean;
  violations: string[];
  policy_version: string;
}

export interface RiskEvaluation {
  blast_radius: string;
  reversible: boolean;
  rationale: string;
}

export interface DecisionRecordOut {
  id: string;
  decision_type: string;
  status: "pending_approval" | "approved" | "rejected" | "shadow";
  context: Record<string, unknown>;
  evidence: Finding[];
  candidates: CandidateRecord[];
  policy_engine_result: PolicyEngineResult;
  risk_evaluation: RiskEvaluation;
  component_versions: Record<string, string>;
  selected_candidate: string | null;
  approved_by: string | null;
  approver_role: Role | null;
  approval_rationale: string | null;
  decided_at: string | null;
  observed_outcome: PolicyEvaluation | null;
  outcome_recorded_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProposeDecisionRequest {
  decision_type: string;
  context: Record<string, unknown>;
  evidence: Finding[];
  scenario: string;
  candidates: CandidateIntervention[];
  eval_seeds?: number[];
  shadow?: boolean;
}

export interface ApproveDecisionRequest {
  approved_by: string;
  approver_role: Role;
  selected_candidate: string;
  rationale: string;
}

export interface RejectDecisionRequest {
  approved_by: string;
  approver_role: Role;
  rationale: string;
}

export interface ObserveOutcomeRequest {
  scenario: string;
  observe_seeds?: number[];
}
