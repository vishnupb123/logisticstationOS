// Live station runtime (backend app/runtime, ADR-0012): one shared simulated
// operating day that every page reads, the agents act on, and the chat
// assistant talks to. Polled once a second through a single TanStack Query
// key, so all mounted pages share one request and stay in lockstep.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { AgentAction, Metric, Risk } from "./stationOps";

export type Mode = "observe" | "advise" | "autopilot";

export interface SessionInfo {
  id: string;
  preset: string;
  seed: number;
  description: string;
  ofd_date: string;
  mode: Mode;
  speed: number;
  paused: boolean;
  complete: boolean;
  minute: number;
  created_at: string;
  source: string;
  default?: boolean;
}

export interface Trip {
  trip_id: string;
  origin: string;
  via_ferry: boolean;
  ferry_sailing: string | null;
  planned_arrival: string;
  eta: string;
  delay_minutes: number;
  revision_count: number;
  delay_reason: string | null;
  status: "in_transit" | "in_yard" | "unloading" | "arrived" | "cancelled";
  door: number | null;
  volume: number;
  actual_arrival: string | null;
  unload_sequence: number | null;
  priority: number;
  arrives_after_pick_start: boolean;
}

export interface RouteRow {
  route_id: string;
  dsp: string;
  cluster: string;
  aisle: string;
  staging_location: string;
  wave: number;
  stage_by: string;
  planned_depart: string;
  original_depart: string;
  moved_waves: number;
  status: "not_ready" | "ready" | "picking" | "staging" | "staged" | "loading" | "departed";
  priority: number;
  sidelined: boolean;
  picker: string | null;
  spr: number;
  spr_flag: "high" | "low" | null;
  bags_done: number;
  bags_total: number;
  carts: number;
  carts_staged: number;
  hv_pending: number;
  pick_minutes: number | null;
  picked: number;
  staged_at: string | null;
  departed_at: string | null;
  depart_late_minutes: number | null;
  projected_stage_at: string | null;
  at_risk: boolean;
  not_attempted: number;
  failed: number;
  driver: string | null;
  driver_state: string | null;
  driver_late_by: number | null;
}

export interface Snapshot {
  minute: number;
  clock: string;
  phase: "pre_shift" | "inbound_induct_stow" | "pick_stage" | "depart" | "on_road" | "complete";
  done: boolean;
  day_complete: boolean;
  scenario: string;
  seed: number;
  ofd_date: string;
  station_code: string;
  cycle: {
    name: string;
    induct_start: string;
    pick_start: string;
    planned_pick_start: string;
    induct_blocked: boolean;
    cutoff_extension_minutes: number;
  };
  package_status: Record<string, number>;
  inbound: Record<string, number>;
  trips: Trip[];
  induct: {
    lines: number;
    active_lines: number;
    down_lines: number[];
    attempts: number;
    inducted: number;
    no_reads: number;
    multi_reads: number;
    misapplied_labels: number;
    damaged: number;
    fph_last_hour: number;
    queue: number;
    problem_queue: number;
  };
  sort: { sorted: number; missorts: number; jackpot: number };
  stow: {
    stowers: number;
    planned_stowers: number;
    stowed: number;
    wip_packages: number;
    wip_minutes: number;
    wip_target_min: number;
    wip_target_max: number;
  };
  outbound: Record<string, number>;
  routes: RouteRow[];
  delivery: Record<string, number>;
  labor: {
    present: number;
    planned: number;
    absent: number;
    flex_remaining: number;
    by_role: Record<string, number>;
  };
  metrics: Record<string, Metric>;
  series: Record<string, number[]>;
  alerts: { severity: "info" | "warning" | "critical"; message: string; area: string }[];
  interventions_applied: {
    kind: string;
    target: string | null;
    clock: string;
    source: string;
    effect: string;
  }[];
}

export interface LineRow {
  line: string;
  status: string;
  inducted: number;
  attempts: number;
  lost_hours: number;
  downtime_dpmo: number;
  no_read_rate: number | null;
  multi_read_rate: number | null;
  misapplied_label_rate: number | null;
  inductor: string | null;
}

export interface AssociateRow {
  login: string;
  role: string;
  home_role: string;
  present: boolean;
  vet: boolean;
  task: string;
  task_ref: string | null;
  picklist: string | null;
  time_since_last_activity: string | null;
  current_task_duration: string | null;
  idle_total: string | null;
  longest_idle: string | null;
  units: number;
  pph: number | null;
  skill: number;
  location: string;
  line: number | null;
  shift_start: string;
  rotation: { clock: string; role: string }[];
}

export interface DriverRow {
  driver_id: string;
  dsp: string;
  route_id: string;
  state: string;
  standby: boolean;
  notified: boolean;
  check_in_due: string;
  expected_check_in: string | null;
  checked_in_at: string | null;
  late_by: number | null;
  no_show_suspected: boolean;
  departed_at: string | null;
  stops_done: number;
  stops_total: number;
  failed: number;
  return_at: string | null;
  swiped: boolean;
  x: number;
  y: number;
  sector: string;
}

export interface DspRow {
  dsp: string;
  routes: number;
  departed: number;
  on_time: number;
  otd: number | null;
  checked_in: number;
  en_route: number;
  late: number;
  no_show_suspected: number;
  pending_swipe: number;
  standby_remaining: number;
  late_rate_plan: number;
}

export interface BacklogPkg {
  tracking_id: string;
  status: string;
  age_days: number;
  resolution: string | null;
}

export interface Views {
  performance: {
    lines: LineRow[];
    top_impacted_by_fph: LineRow[];
    top_impacted_by_lost_hours: LineRow[];
    top_impacted_by_dpmo: LineRow[];
    top_quality_issues: { issue: string; line: string; rate: number }[];
  };
  receive: Record<string, number> & { doors: { door: number; trip: string | null }[] };
  dwell: {
    columns: string[];
    by_cycle: Record<string, string | number>[];
    windows: string[];
    by_window: Record<string, string | number>[];
  };
  ageing: {
    buckets: string[];
    rows: Record<string, string | number>[];
    missing_packages: BacklogPkg[];
    lost_packages: BacklogPkg[];
    scrubs: { kind: string; minute: number; resolved: number }[];
  };
  rts: {
    types: string[];
    inbound: Record<string, number>;
    currently_at_station: Record<string, number>;
    delivery_cancelled: number;
    totals: Record<string, number>;
  };
  stow_buffers: {
    buffer: string;
    status: string;
    full_bays: number;
    bays: number;
    jackpot: number;
    jackpot_rate: number | null;
    no_read_rate: number | null;
    current_volume: number;
    capacity: number;
    pct_station_volume: number;
    avg_pph: number;
  }[];
  associates: { rows: AssociateRow[]; summary: Record<string, number> & { by_role: Record<string, number> } };
  pick: Record<string, number | null>;
  stage: Record<string, number | null>;
  dispatch: {
    dsps: DspRow[];
    drivers: DriverRow[];
    map: {
      zones: { route_id: string; x: number; y: number; dsp: string }[];
      incidents: { target: string | null; magnitude: number; clock: string }[];
      extent_km: number;
    };
  };
  high_value: {
    total: number;
    pending_scan_in: number;
    in_cage: number;
    handed_off: number;
    dispatched: number;
    rolled_over: number;
    custody_compliance: number | null;
    avg_cage_dwell_minutes: number | null;
    queue: number;
    associates: string[];
    packages: {
      tracking_id: string;
      route_id: string;
      status: string;
      custody_scans: number;
      location: string | null;
      cage_minutes: number | null;
    }[];
  };
  labor_plan: {
    ofd_date: string;
    cycle: string;
    total_volume: number;
    planned_volume: number;
    forecast_unplanned: number;
    sideline_rts: number;
    planned_rollover: number;
    total_show_hours: number;
    total_needed_hours: number;
    needed_by_function: Record<string, number>;
    planned_tph: number;
    work_groups: {
      time: string;
      work_group: string;
      attendance: number | null;
      expected_headcount: number;
      present: number;
      expected_show_hours: number;
    }[];
    vet_opportunities: number;
    vto_opportunities: number;
    flex_remaining: number;
  };
  problem_solve: {
    queue: number;
    by_reason: Record<string, number>;
    resolved: number;
    associates: string[];
    items: { tracking_id: string; reason: string; route_id: string }[];
  };
  work_items: {
    area: string;
    priority: "high" | "normal";
    title: string;
    action: StationAction | null;
  }[];
  layout: {
    aisles: { aisle: string; level: number; capacity: number }[];
    staging: { location: string; status: string }[];
    doors: { door: number; trip: string | null }[];
    lines: { line: string; status: string }[];
  };
  sort_paths: { partition: string; cycle: string; grid: string; overlaps: string[] }[];
  devices: {
    handhelds: { device: string; assigned_to: string; battery: number; status: string }[];
    scanners: { device: string; read_rate: number; status: string }[];
  };
  events: { clock: string; kind: string; message: string; source?: string }[];
}

export interface LiveState {
  snapshot: Snapshot;
  views: Views;
  session: SessionInfo;
  agents: {
    mode: Mode;
    busy: boolean;
    risks: Risk[];
    actions: (AgentAction & { id: number; agent: string; agent_label: string; kind: string; status: string })[];
    pending: (AgentAction & { id: number; agent: string; agent_label: string; kind: string; status: string })[];
  };
}

export interface StationAction {
  kind: string;
  target?: string | null;
  amount?: number;
  params?: Record<string, unknown>;
  source?: string;
}

export interface ChatReply {
  reply: string;
  intent: string;
  actions: Record<string, unknown>[];
  data: Record<string, unknown>;
  understood_by: "rules" | "llm" | "none";
}

const SID = "default";

export const runtimeApi = {
  state: () => api.get<LiveState>(`/runtime/sessions/${SID}/state`),
  sessions: () => api.get<SessionInfo[]>("/runtime/sessions"),
  create: (body: { preset: string; seed?: number | null; mode: Mode; speed: number; source?: string; ofd_date?: string }) =>
    api.post<SessionInfo>("/runtime/sessions", body),
  control: (body: { paused?: boolean; speed?: number; mode?: Mode }) =>
    api.post<SessionInfo>(`/runtime/sessions/${SID}/control`, body),
  act: (action: StationAction) =>
    api.post<{ effect: string; clock: string }>(`/runtime/sessions/${SID}/actions`, {
      amount: 1,
      ...action,
      source: action.source ?? "ui",
    }),
  decide: (id: number, verb: "approve" | "dismiss") =>
    api.post<unknown>(`/runtime/sessions/${SID}/recommendations/${id}/${verb}`),
  chat: (message: string) => api.post<ChatReply>(`/runtime/sessions/${SID}/chat`, { message }),
  chatHistory: () =>
    api.get<{ role: "user" | "assistant"; text: string; intent?: string }[]>(`/runtime/sessions/${SID}/chat`),
  search: (q: string) =>
    api.get<{ kind: string; results: Record<string, unknown>[] }>(
      `/runtime/sessions/${SID}/search?q=${encodeURIComponent(q)}`,
    ),
};

/** The one live-state subscription every page shares. */
export function useStation() {
  return useQuery({
    queryKey: ["live-state"],
    queryFn: runtimeApi.state,
    refetchInterval: 1000,
    refetchIntervalInBackground: false,
  });
}

/** Apply an action to the live (simulated) station; result surfaces as a toast-like message. */
export function useStationAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runtimeApi.act,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live-state"] }),
  });
}

export function useControl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: runtimeApi.control,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live-state"] }),
  });
}

export function pctv(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

export const STATUS_LABEL: Record<string, string> = {
  not_ready: "Not ready",
  ready: "Not assigned",
  picking: "Picking",
  staging: "Partially staged",
  staged: "Staged",
  loading: "Loading",
  departed: "Departed",
};
