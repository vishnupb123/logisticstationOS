// Station Operations: full-day twin (live SSE + what-if runs), daily
// truckfile with ferry refresh, and the Station Operations Agent.
// Types mirror backend/app/simulation/station_ops/snapshot.py,
// backend/app/agents/station_ops/*.py and backend/app/api/routes/station_ops.py
// by hand (no codegen) — keep them in sync.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, BASE_URL } from "./client";
import type { AgentExecutionDetail, AgentExecutionSummary, EvidenceCategory } from "./types";

export type AgentMode = "observe" | "advise" | "autopilot";
export type Source = "preset" | "truckfile";

export interface Metric {
  key: string;
  value: number | null;
  target: number | null;
  unit: "ratio" | "count" | "per_hour" | "minutes" | "hours";
}

export interface Trip {
  trip_id: string;
  origin: string;
  via_ferry: boolean;
  ferry_sailing: string | null;
  planned_arrival: string;
  eta: string;
  eta_minute: number;
  delay_minutes: number;
  delay_reason: string | null;
  status: "in_transit" | "unloading" | "arrived" | "cancelled";
  door: number | null;
  volume: number;
  arrives_after_pick_start: boolean;
}

export interface RouteRow {
  route_id: string;
  dsp: string;
  staging_location: string;
  stage_by: string;
  planned_depart: string;
  status: "not_ready" | "picking" | "picked" | "staged" | "departed";
  packages: number;
  picked: number;
  staged_at: string | null;
  departed_at: string | null;
  depart_late_minutes: number | null;
  projected_stage_at: string | null;
  at_risk: boolean;
  not_attempted: number;
}

export interface AppliedIntervention {
  kind: string;
  amount: number;
  minute: number;
  clock: string;
  source: string;
  effect: string;
}

export interface StationSnapshot {
  frame: number;
  minute: number;
  clock: string;
  phase: "pre_shift" | "inbound_induct_stow" | "pick_stage" | "depart" | "complete";
  done: boolean;
  scenario: string;
  seed: number;
  ofd_date: string;
  station_code: string;
  cycle: {
    name: string;
    induct_start: string;
    pick_start: string;
    pick_start_minute: number;
    planned_pick_start: string;
    induct_blocked: boolean;
    cutoff_extension_minutes: number;
  };
  package_status: Record<string, number>;
  inbound: {
    trips_planned: number;
    trips_arrived: number;
    trips_late: number;
    trips_cancelled: number;
    planned_volume: number;
    arrived_volume: number;
    late_volume_after_pick_start: number;
  };
  trips: Trip[];
  induct: {
    lines: number;
    active_lines: number;
    down_lines: number[];
    attempts: number;
    inducted: number;
    no_reads: number;
    multi_reads: number;
    no_read_rate: number | null;
    multi_read_rate: number | null;
    fph_last_hour: number;
    queue: number;
  };
  sort: { sorted: number; missorts: number };
  stow: {
    stowers: number;
    planned_stowers: number;
    stowed: number;
    wip_packages: number;
    wip_minutes: number;
    wip_target_min: number;
    wip_target_max: number;
  };
  outbound: {
    routes_total: number;
    not_ready: number;
    picking: number;
    picked: number;
    staged: number;
    departed: number;
    at_risk: number;
    pickers: number;
    avg_pick_minutes: number | null;
  };
  routes: RouteRow[];
  delivery: { promised: number; attempted: number; not_attempted: number; known_misses: number };
  metrics: Record<string, Metric>;
  series: Record<"minute" | "arrived" | "inducted" | "stowed" | "wip_minutes" | "departed_routes", number[]>;
  alerts: { severity: "info" | "warning" | "critical"; message: string }[];
  interventions_applied: AppliedIntervention[];
  source_kind: "simulated";
}

export interface Risk {
  risk_type: string;
  agent?: string;
  severity: "info" | "warning" | "critical";
  category: EvidenceCategory;
  summary: string;
  metric: string;
  projected_impact: number;
  detected_at_minute: number;
  evidence: Record<string, unknown>;
}

export interface Outcome {
  dea: number;
  otd: number;
  timely_staged: number;
  rolled_over: number;
  left_behind: number;
  not_attempted: number;
}

export interface Evaluation {
  name: string;
  interventions: { kind: string; amount: number; at_minute: number; source: string }[];
  labor_hours: number;
  outcome: Outcome;
  delta_dea_pp: number;
  delta_otd_pp: number;
  delta_timely_staged_pp: number;
  score: number;
  score_stdev?: number;
  futures?: number;
}

export interface AgentAction {
  id?: number;
  agent?: string;
  agent_label?: string;
  kind?: string;
  status?: string;
  deferred?: string[];
  minute: number;
  clock: string;
  mode: AgentMode;
  risk: Risk;
  baseline: Outcome | null;
  evaluations: Evaluation[];
  learned_skips: string[];
  chosen: string | null;
  applied: boolean;
  applied_effects: string[];
  advisory: string | null;
  rationale: string;
}

export interface Frame {
  snapshot: StationSnapshot;
  agent: { mode: AgentMode; risks: Risk[]; new_actions: AgentAction[]; actions_total: number };
}

export interface Preset {
  name: string;
  description: string;
}

export interface MetricDefinitions {
  metrics: Record<string, { label: string; formula: string; status: string }>;
  score_weights: Record<string, number>;
  score_version: string;
  lever_limits: Record<string, number>;
}

export interface TruckfileTrip {
  trip_id: string;
  origin: string;
  via_ferry: boolean;
  ferry_sailing: string | null;
  planned_arrival: string;
  revised_arrival: string | null;
  volume: number;
  cycle: string;
  ferry_status: "not_applicable" | "unknown" | "on_time" | "delayed" | "cancelled";
  delay_minutes: number;
  delay_reason: string | null;
  last_checked_at: string | null;
  checks: number;
  source_kind: string;
}

export interface RefreshSummary {
  ofd_date: string;
  provider: string;
  checked_at: string;
  ferry_trips: number;
  delayed: number;
  cancelled: number;
  volume_at_risk: number;
  changes: { trip_id: string; sailing: string; from: unknown[]; to: unknown[] }[];
}

export interface PlaybookStat {
  risk_type: string;
  situation: string;
  lever_key: string;
  candidate_name: string;
  episodes: number;
  scenarios: string[];
  mean_score: number;
  mean_delta_dea_pp: number;
  mean_delta_otd_pp: number;
  mean_delta_timely_staged_pp: number;
  win_rate: number;
}

export interface LlmStatus {
  provider: string;
  model: string;
  base_url: string;
  available: boolean;
}

export const stationOpsApi = {
  presets: () => api.get<Preset[]>("/station-ops/presets"),
  metricDefinitions: () => api.get<MetricDefinitions>("/station-ops/metric-definitions"),
  truckfile: (ofdDate: string) =>
    api.get<{ ofd_date: string; exists: boolean; trips: TruckfileTrip[] }>(
      `/inbound/truckfile?ofd_date=${ofdDate}`,
    ),
  refreshTruckfile: (body: { ofd_date: string; weather?: string | null; seed?: number }) =>
    api.post<{ summary: RefreshSummary; trips: TruckfileTrip[] }>("/inbound/truckfile/refresh", body),
  runAgent: (body: {
    preset: string;
    seed: number;
    source: Source;
    ofd_date?: string | null;
    until_minute?: number;
    propose_decisions?: boolean;
  }) =>
    api.post<{ execution: AgentExecutionDetail; decision_ids: string[] }>(
      "/agents/station-ops/run",
      body,
    ),
  executions: () => api.get<AgentExecutionSummary[]>("/agents/station-ops/executions"),
  execution: (id: string) => api.get<AgentExecutionDetail>(`/agents/station-ops/executions/${id}`),
  playbook: () =>
    api.get<{ episodes: number; stats: PlaybookStat[]; note: string }>("/agents/station-ops/playbook"),
  llmStatus: () => api.get<LlmStatus>("/llm/status"),
};

export type StreamStatus = "idle" | "connecting" | "streaming" | "complete" | "stopped" | "error";

export interface StreamParams {
  preset: string;
  seed: number;
  mode: AgentMode;
  source: Source;
  ofdDate?: string;
  stepMinutes: number;
  frameIntervalMs: number;
  learn: boolean;
}

/** SSE hook for GET /station-ops/live. Keeps the latest snapshot plus the
 * full agent action log (actions arrive once, in the frame they happen). */
export function useStationStream() {
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [frame, setFrame] = useState<Frame | null>(null);
  const [actions, setActions] = useState<AgentAction[]>([]);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<EventSource | null>(null);

  const close = useCallback(() => {
    ref.current?.close();
    ref.current = null;
  }, []);

  const start = useCallback(
    (p: StreamParams) => {
      close();
      setFrame(null);
      setActions([]);
      setError(null);
      setStatus("connecting");
      const q = new URLSearchParams({
        preset: p.preset,
        seed: String(p.seed),
        mode: p.mode,
        source: p.source,
        step_minutes: String(p.stepMinutes),
        frame_interval_ms: String(p.frameIntervalMs),
        learn: String(p.learn),
      });
      if (p.source === "truckfile" && p.ofdDate) q.set("ofd_date", p.ofdDate);
      const es = new EventSource(`${BASE_URL}/station-ops/live?${q}`);
      ref.current = es;
      es.addEventListener("frame", (ev) => {
        const f = JSON.parse((ev as MessageEvent).data) as Frame;
        setStatus("streaming");
        setFrame(f);
        if (f.agent.new_actions.length) setActions((prev) => [...prev, ...f.agent.new_actions]);
      });
      es.addEventListener("end", () => {
        es.close();
        ref.current = null;
        setStatus("complete");
      });
      es.onerror = () => {
        if (ref.current !== es) return;
        es.close();
        ref.current = null;
        setStatus("error");
        setError("Lost the stream — the backend may be down or rejected the parameters.");
      };
    },
    [close],
  );

  const stop = useCallback(() => {
    close();
    setStatus((s) => (s === "streaming" || s === "connecting" ? "stopped" : s));
  }, [close]);

  useEffect(() => close, [close]);
  return { status, frame, actions, error, start, stop };
}

export const RISK_LABEL: Record<string, string> = {
  yard_congestion: "Yard congestion",
  problem_solve_backlog: "Problem-solve backlog",
  driver_late: "Drivers projected late",
  driver_no_show: "Driver no-show",
  pending_swipe: "Drivers pending swipe",
  wave_checkin_upcoming: "Wave check-in reminders",
  traffic_incident: "Traffic incident",
  hv_backlog: "High-value cage backlog",
  late_linehaul_rollover: "Late linehaul → rollover",
  induct_capacity_shortfall: "Induct capacity shortfall",
  stow_capacity_shortfall: "Stow capacity shortfall",
  induct_line_down: "Induct line down",
  routes_at_risk: "Routes at risk of stage-by",
  stow_wip_above_band: "Stow WIP above band",
  stow_wip_below_band: "Stow WIP below band",
  sort_compliance_below_target: "Sort compliance below target",
  scan_compliance_below_target: "Scan compliance below target",
};

export function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

export function signed(v: number, digits = 2, unit = "pp"): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}${unit}`;
}

export function clockOf(minute: number): string {
  const m = Math.round(minute);
  return `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
