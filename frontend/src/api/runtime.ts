// Live station runtime (backend app/runtime, ADR-0012): one shared simulated
// operating day that every page reads, the agents act on, and the chat
// assistant talks to. Polled once a second through a single TanStack Query
// key, so all mounted pages share one request and stay in lockstep.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { ViewsV2 } from "./runtimeV2";
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
  day: number;
  truckfile_version: number | null;
  next_day_ready: boolean;
  scale?: number;
  pitch?: boolean;
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
  phase: "pre_shift" | "inbound_induct_stow" | "pick_stage" | "depart" | "closeout" | "on_road" | "complete";
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
  vsa: string | null;
  vsa_defect: string | null;
  van_request: string | null;
  van_eta: string | null;
}

export interface Notification {
  id: number;
  minute: number;
  clock: string;
  audience: "supervisor" | "manager" | "dsp" | "driver";
  kind: string;
  severity: "info" | "warning" | "critical";
  title: string;
  message: string;
  ack: boolean;
  acked_at: string | null;
  route_id?: string;
  aisle?: string;
  dsp?: string;
}

export interface YardRow {
  driver_id: string;
  dsp: string;
  route_id: string;
  checked_in: string | null;
  state: string;
  result: string | null;
  defect: string | null;
  wait_minutes: number;
  audited_at: string | null;
  van_request: string | null;
  van_eta: string | null;
  grounded_for: number | null;
}

export interface StagingLoc {
  location: string;
  row: string;
  slot: number;
  route_id: string;
  wave: number;
  dsp: string;
  status: RouteRow["status"];
  carts: number;
  carts_staged: number;
  hv_pending: number;
  stage_by: string;
  depart: string;
  driver: string | null;
  driver_state: string | null;
  foreign_cart: string | null;
  misstaged_at: string | null;
  risk: string | null;
}

export interface AisleCell {
  aisle: string;
  cluster: string;
  index: number;
  level: number;
  capacity: number;
  routes: { route_id: string; status: string; wave: number }[];
  picked: number;
  people: { login: string; task: string; role: string }[];
  sweep: "sweeping" | "due" | "swept" | null;
  swept_at: string | null;
  flagged_left_behind: number;
  left_behind_true: number;
}

export interface CloseoutTask {
  id: number;
  owner: "supervisor" | "manager";
  kind: string;
  title: string;
  minutes: number;
  priority: number;
  status: "queued" | "in_progress" | "done";
  created_clock: string;
  finished_clock?: string;
  started: number | null;
  result: string | null;
}

export interface Gtdr {
  gtdr_id: string;
  direction: "inbound_late" | "outbound_pallet";
  trailer: string;
  place: string;
  scheduled: string;
  actual: string;
  delay_minutes: number;
  door: number | null;
  units: number;
  pallets: number;
  reason: string;
  seal: string;
  status: "open" | "drafted" | "filed";
  opened_clock: string;
  filed_clock: string | null;
}

export interface NeedsPlan {
  routes: number;
  spr: number;
  tph: number;
  by_role: Record<string, number>;
  headcount: number;
  labor_hours: number;
}

export interface Closeout {
  started: boolean;
  started_at: string | null;
  complete: boolean;
  tomorrow: string;
  now: string;
  tasks: CloseoutTask[];
  gtdr: Gtdr[];
  truckfile: {
    version: number;
    final_published_at: string | null;
    final_due: string;
    trips: {
      trip_id: string;
      origin: string;
      via_ferry: boolean;
      sailing: string | null;
      planned_arrival: string;
      eta: string;
      delay_minutes: number;
      volume: number;
      cancelled: boolean;
      added: boolean;
      last_checked: string | null;
      after_pick_start: boolean;
    }[];
    log: {
      clock: string;
      trip_id: string;
      field: string;
      before: number | boolean;
      after: number | boolean;
      why: string;
      how: string;
      after_final: boolean;
      version: number;
    }[];
    ferry_checks: { clock: string; changes: number }[];
  };
  ofd: Record<string, number> | null;
  needs: NeedsPlan | null;
  show: Record<string, number> | null;
  gap: number | null;
  offers: {
    login: string;
    type: "vet" | "vto";
    offered_clock: string;
    status: "pending" | "accepted" | "declined";
    responded_clock: string | null;
    source: string;
  }[];
  callouts: { clock: string; login: string }[];
  plan:
    | (Record<string, unknown> & {
        version: number;
        clock: string;
        truckfile_version: number;
        needs: NeedsPlan;
        show: Record<string, number>;
        ofd: Record<string, number>;
        gap: number;
        aisles: { aisle: string; volume: number; routes: number }[];
        zones: { zone: string; aisles: string; volume: number }[];
        assignments: {
          role: string;
          where: string;
          login: string | null;
          ok: boolean;
          vet?: boolean;
          history?: string[];
          note: string;
        }[];
        rotation_violations: number;
        rotation_compliance: number;
      })
    | null;
  plan_history: {
    version: number;
    clock: string;
    label: string;
    truckfile_version: number;
    ofd_volume: number;
    headcount_needed: number;
    expected: number;
    gap: number;
  }[];
  scrubs: Record<string, Record<string, string | number>>;
  readiness: Record<string, number | boolean | null> | null;
}

export interface CityMap {
  extent_km: number;
  roads: { kind: "highway" | "ring" | "street"; points: [number, number][]; bridge?: boolean }[];
  river: [number, number][];
  bridges: [number, number][];
  neighbourhoods: { name: string; x: number; y: number }[];
  parks: { x: number; y: number; r: number }[];
  zones: { route_id: string; x: number; y: number }[];
}

export interface DriverPath {
  driver_id: string;
  route_id: string;
  state: string;
  to_station: [number, number][];
  out: [number, number][];
  tour: [number, number][];
  back: [number, number][];
  stops_done_display: number;
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
  yard: {
    marshals: number;
    extra_marshals: number;
    queue: number;
    booked_ahead_minutes: number;
    audited: number;
    passed: number;
    minor_fixed: number;
    grounded: number;
    grounded_now: number;
    spare_vans: Record<string, number>;
    rows: YardRow[];
  };
  staging_floor: {
    rows: string[];
    slots: number;
    locations: StagingLoc[];
    waves: { wave: number; stage_by: string; routes: number; staged: number; departed: number; at_risk: number }[];
    risks: Record<string, number>;
  };
  aisle_plan: {
    aisles: AisleCell[];
    clusters: string[];
    sweep_log: {
      clock: string;
      aisle: string;
      route_id: string;
      packages: number;
      reasons: string[];
      outcome: "staged" | "cluster_transfer";
      by: string;
    }[];
    swept: number;
    sweep_recovered: number;
    cluster_transfer: number;
  };
  notifications: { items: Notification[]; unacked: Record<string, number>; critical_unacked: number };
  closeout: Closeout;
}

export interface LiveState {
  snapshot: Snapshot;
  views: Views & ViewsV2;
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

export interface ChatSource {
  kind: string;
  title: string;
  clock?: string | null;
}

export interface ChatReply {
  reply: string;
  intent: string;
  actions: Record<string, unknown>[];
  data: Record<string, unknown>;
  understood_by: "rules" | "llm" | "none";
  title?: string | null;
  sections?: { title: string; lines: string[] }[];
  sources?: ChatSource[];
  llm_summary?: string | null;
  llm_status?: "grounded" | "withheld" | "unavailable" | "skipped";
}

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
  intent?: string;
  title?: string | null;
  sections?: { title: string; lines: string[] }[];
  sources?: ChatSource[];
  llm_summary?: string | null;
  llm_status?: string;
}

const SID = "default";

export const runtimeApi = {
  state: () => api.get<LiveState>(`/runtime/sessions/${SID}/state`),
  sessions: () => api.get<SessionInfo[]>("/runtime/sessions"),
  create: (body: { preset?: string; seed?: number | null; mode: Mode; speed: number; source?: string; ofd_date?: string; scale?: number }) =>
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
  chatHistory: () => api.get<ChatTurn[]>(`/runtime/sessions/${SID}/chat`),
  map: () => api.get<CityMap>(`/runtime/sessions/${SID}/map`),
  driverPath: (id: string) => api.get<DriverPath>(`/runtime/sessions/${SID}/drivers/${encodeURIComponent(id)}/path`),
  ack: (id: number) => api.post<Notification>(`/runtime/sessions/${SID}/notifications/${id}/ack`),
  ackAll: (audience: string) => api.post<{ acked: number }>(`/runtime/sessions/${SID}/notifications/ack-all`, { audience }),
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
