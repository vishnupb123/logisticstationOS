// StationOS v2 runtime contract (HANDOFF_V2): the extra page views the backend
// adds to /runtime/sessions/{id}/state (`views.*`) and the v2 endpoints.
// Types mirror backend/app/simulation/station_ops/views_v2.py, status.py,
// metrics.py and app/runtime/session.py. Synthetic data only.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

const SID = "default";

export type Provenance = "documented" | "observed" | "proposed";

export interface MetricSpec {
  label: string;
  status: Provenance;
  formula: string;
  unit: string;
}

/** Inputs exposed by the metric engine for the "How this is calculated" drawer. */
export type MetricInputs = Record<string, unknown>;

// --- receive -----------------------------------------------------------------------
export interface StatusLadder {
  manifested: number;
  in_transit: number;
  arrived: number;
  marked_for_reprocess: number;
  inducted: number;
  stow_buffered: number;
  stowed: number;
  sidelined: number;
}
export interface ReceiveCycle {
  predicted_dispatch: number;
  current_cycle_planned: number;
  current_cycle_arrived: number;
  other_unplanned_arrived: number;
  total_arrived: number;
  planned: StatusLadder;
  unplanned: StatusLadder;
}
export interface TripLeg {
  from: string;
  to: string;
  mode: "road" | "ferry";
  planned_depart: number;
  planned_arrive: number;
  planned_depart_clock: string;
  planned_arrive_clock: string;
  eta_clock: string;
  state: "done" | "active" | "planned";
}
export interface ContainerRow {
  id: string;
  type: "GAYLORD" | "PALLET";
  pending_induct: number;
  total: number;
  unloaded?: boolean;
  clusters?: Record<string, number>;
}
export type GroupByKey = "none" | "package_size" | "destination" | "station_ead" | "cycle" | "cluster";
export interface LinehaulV2 {
  trip_id: string;
  origin: string;
  status: "In Yard" | "Arrived" | "Pending Depart" | "In-Transit" | "Cancelled";
  location: string | null;
  planned: string;
  planned_minute: number;
  eta: string;
  actual: string | null;
  volume: number | null;
  unload_sequence: number | null;
  via_ferry: boolean;
  operator_type: "single" | "team";
  tractor: string | null;
  trailer: string | null;
  legs: TripLeg[];
  issues: { kind: string; text: string }[];
  watched: boolean;
  group: Record<Exclude<GroupByKey, "none">, Record<string, number>>;
  containers: ContainerRow[];
  unplanned_share: number;
}
export interface ReceiveV2 {
  cycles: Record<"CYCLE_1" | "High_Value", ReceiveCycle>;
  linehauls: LinehaulV2[];
  watch: string[];
  group_by: GroupByKey[];
}

// --- induct / stow -------------------------------------------------------------------
export interface InductOverall {
  current_cycle_planned: number;
  current_cycle_inducted: number;
  other_unplanned_inducted: number;
  total_inducted: number;
  manifested: number;
  arrived: number;
  marked_for_reprocess: number;
  inducted: number;
  stow_buffered: number;
  stowed: number;
  sidelined: number;
}
export interface InductArea {
  line: string;
  type: "Automated" | "Manual";
  status: "Running" | "Down" | "Unstaffed";
  down_reason: string | null;
  inductor: string | null;
  target_pph: number;
  pph_last_hour: number;
  inducted: number;
  lost_hours: number;
  stops: number;
  no_read: number;
  multi_read: number;
  misapplied_label: number;
}
export interface InductV2 {
  overall: Record<"CYCLE_1" | "High_Value" | "Unplanned", InductOverall>;
  areas: InductArea[];
  containers: { linehaul: string; containers: ContainerRow[] }[];
  noncon_queue: number;
  noncon_total: number;
}
export interface StowCluster {
  cluster: string;
  planned: number;
  arrived: number;
  inducted: number;
  stow_buffered: number;
  stowed: number;
  stow_plan: number | null;
  ps: number;
  jackpot_buffered: number;
  unopened_bags: number;
  minutes_of_work: number | null;
  stow_rate: number;
  scan_compliance: number;
  active_stowers: number;
}
export interface Finger {
  machine: string;
  status: "Active" | "Down";
  clusters: string[];
  rebalanced_to: string | null;
  buffer: number;
  bay_capacity: number;
  full_bay: boolean;
  full_bay_events: number;
  jackpot_rate: number | null;
  no_read_rate: number | null;
  current_volume: number;
  volume: number;
  pct_station_volume: number;
  avg_pph: number;
}
export interface StowV2 {
  clusters: StowCluster[];
  fingers: Finger[];
}

// --- package status tree -------------------------------------------------------------
export interface StatusRow {
  status: string;
  [column: string]: string | number;
}
export interface StatusGroup {
  group: string;
  rows: StatusRow[];
  [column: string]: string | number | StatusRow[];
}
export interface StatusTree {
  by: "cycle" | "window";
  columns: string[];
  groups: StatusGroup[];
  total: number;
}
export interface AgeingRow {
  status: string;
  total: number;
  [bucket: string]: string | number;
}
export interface AgeingGroup {
  group: string;
  rows: AgeingRow[];
  total: number;
  [bucket: string]: string | number | AgeingRow[];
}
export interface AgeingV2 {
  buckets: string[];
  forward: AgeingGroup[];
  reverse: AgeingGroup[];
  missing_packages: { tracking_id: string; status: string; age_days: number; resolution: string | null }[];
  lost_packages: { tracking_id: string; status: string; age_days: number; resolution: string | null }[];
  scrubs: { kind: string; minute: number; resolved: number }[];
}
export interface PackageListItem {
  tracking_id: string;
  group: string;
  status: string;
  cycle: string;
  route: string;
  container: string | null;
  planned: boolean;
  location: string | null;
}

// --- plan vs actual ------------------------------------------------------------------
export interface PvaInterval {
  start: number;
  label: string;
  receive_planned: number;
  receive_actual: number | null;
  induct_planned: number;
  induct_actual: number | null;
  induct_auto_planned: number;
  induct_auto_actual: number | null;
  induct_manual_planned: number;
  induct_manual_actual: number | null;
  stow_planned: number;
  stow_actual: number | null;
  pick_planned: number;
  pick_actual: number | null;
  labor: Record<string, number | null>;
  stowers: number | null;
}
export interface PlanTotals {
  show_hours: number;
  needed_hours: number;
  tph_with_indirect: number | null;
  tph_without_indirect: number | null;
  indirect_allowance: number;
}
export interface PlanVsActual {
  intervals: PvaInterval[];
  target_induct_pph: number;
  target_stow_pph: number;
  labor_groups: string[];
  plan_totals: PlanTotals;
  note: string;
}

// --- associates by path --------------------------------------------------------------
export interface InductAssoc {
  associate: string;
  pph: number | null;
  hours: number;
  total_packages: number;
  active: boolean;
  location: string;
}
export interface StowAssoc {
  associate: string;
  pph: number | null;
  hours: number;
  total_packages: number;
  fsaf: number;
  fsaf_dpmo: number | null;
  stow_scan_to_ps: number;
  spot_checks: number;
  spot_check_dpmo: number | null;
  active: boolean;
  last_location: string;
  cluster: string | null;
}
export interface PickAssoc {
  associate: string;
  picklist_assigned: boolean;
  time_since_last_activity_min: number | null;
  picklist_id: string | null;
  current_picklist_minutes: number | null;
  idle_between_picklists_min: number;
  last_location: string;
  hours: number;
  units: number;
}
export interface AssociatePerformance {
  induct: InductAssoc[];
  stow: StowAssoc[];
  pick: PickAssoc[];
  pick_summary: { total: number; with_picklist: number; without_picklist: number };
  governance: string;
}

// --- shift plan / opportunities / rotation --------------------------------------------
export interface WorkGroupRow {
  name: string;
  window: string;
  start_minute: number;
  end_minute: number;
  attendance: number;
  scheduled: number;
  needed_peak: number;
  expected_headcount: number;
  expected_show_hours: number;
  paths: string[];
  roster_given?: boolean;
}
export interface PathRow {
  path: string;
  label: string;
  hc: number[];
  hours: number;
}
export interface PlanGroup {
  group: string;
  hc: number[];
  volume: number[];
  paths: PathRow[];
}
export interface LaborPlanV2 {
  cycles: { cycle: string; total_volume: number; planned_volume: number; sideline_rts: number; planned_rollover: number }[];
  totals: PlanTotals;
  work_groups: WorkGroupRow[];
  hours: string[];
  hour_minutes: number[];
  total_volume: number[];
  groups: PlanGroup[];
  needed_by_hour: number[];
  available_by_hour: number[];
  gap_by_hour: number[];
  provenance: string;
}
export interface Opportunity {
  id: string;
  type: "VET" | "VTO";
  frame: string;
  time_frame: string;
  frame_start: number;
  headcount: number;
  posted_at: number;
  posted_clock: string;
  window_close: number;
  window_close_clock: string;
  status: "open" | "closed";
  window: "Open" | "Closed";
  submitted: number;
  accepted: number;
  source: string;
  submissions: { login: string; clock: string }[];
  closed_clock?: string;
  closed_reason?: string;
}
export interface OpportunitiesView {
  opportunities: Opportunity[];
  recommendations: { type: "VET" | "VTO"; frame: string; time_frame: string; headcount: number }[];
  rule: string;
  signup_window_minutes: number;
}
export interface RotationRow {
  login: string;
  rotation_priority: "High" | "Low" | "None";
  disallowed_paths: string[];
  trained_paths: string[];
  history: string[];
  recommended_path: string | null;
  flex: boolean;
  vet: boolean;
  vto: boolean;
  called_out: boolean;
}
export interface ShiftPlanV2 {
  pre_shift: LaborPlanV2;
  next_day: LaborPlanV2 | null;
  next_day_version: number | null;
  next_day_label: string;
  opportunities: OpportunitiesView;
  rotation: {
    rows: RotationRow[];
    stats: { solver?: string; slots?: number; filled?: number; unfilled?: number; violations?: number; compliance?: number; runs?: number; clock?: string; rerun?: boolean };
    run: boolean;
    max_consecutive: number;
    disallow_rule: string;
  };
  ofd_date: string;
}

// --- cycles / settings / work items / chapters -------------------------------------
export interface CycleRow {
  cycle: string;
  assigned_node: string;
  force_induct: boolean;
  force_until?: string | null;
  active_until: string | null;
  dynamic_plan: boolean;
  induct_blocked: boolean;
}
export interface CyclesView {
  banner: string | null;
  cycles: CycleRow[];
  pick_started: boolean;
  pick_start: string;
  on_floor_missed_cycle: number;
  next_cycle: number;
  held_wrong_cycle: number;
  force_staged: number;
  changes: { clock: string; action: string; packages?: number; minutes?: number; hours?: number }[];
  delivery_windows: string[];
  max_force_induct_minutes: number;
}
export interface SettingsView {
  values: Record<string, unknown> & {
    stow_wip_lower_min: number;
    stow_wip_upper_min: number;
    stow_wip_compliance_target: number;
    induct_dwell_minutes: number;
    breaks: { start_minute: number; minutes: number; label: string }[];
  };
  editable: string[];
  provenance: Record<string, string>;
  site_profile: Record<string, unknown>;
}
export interface WorkItem {
  id: string;
  kind: string;
  category: string;
  process: string;
  priority: 1 | 2 | 3;
  title: string;
  owner: string;
  associate: string | null;
  started_by: "system" | "agent" | "person" | string;
  ref: string | null;
  created: number;
  created_clock: string;
  expires_at: number;
  expires_clock: string;
  state: "pending" | "done" | "expired" | "dismissed";
  closed_clock?: string | null;
  resolution?: string | null;
  carried?: boolean;
  recommendation_id?: number;
}
export interface WorkItemsView {
  summary: {
    pending: number;
    by_category: Record<string, number>;
    high_priority: number;
    completed_today: number;
    expired_today: number;
    dismissed_today: number;
    carried_over: number;
    agent_recommendations?: number;
  };
  items: WorkItem[];
}
export interface Chapter {
  minute: number;
  clock: string;
  title: string;
}

/** The v2 additions to `views` in the live state. */
export interface ViewsV2 {
  receive_v2: ReceiveV2;
  induct_v2: InductV2;
  stow_v2: StowV2;
  dwell_v2: { by_cycle: StatusTree; by_window: StatusTree };
  ageing_v2: AgeingV2;
  plan_vs_actual: PlanVsActual;
  associate_performance: AssociatePerformance;
  shift_plan_v2: ShiftPlanV2;
  cycles: CyclesView;
  settings: SettingsView;
  work_items_v2: WorkItemsView;
  metric_specs: Record<string, MetricSpec>;
  chapters: Chapter[];
}

export interface ShiftReport {
  session: Record<string, unknown>;
  metrics: Record<string, { key: string; value: number | null; target: number | null; unit: string; inputs?: MetricInputs }>;
  dea: { topic: string; title: string; headline: string; sections: { title: string; lines: string[] }[] };
  otd: { topic: string; title: string; headline: string; sections: { title: string; lines: string[] }[] };
  work_items: WorkItemsView["summary"];
  cycles: CyclesView;
  tomorrow: {
    truckfile_version: number;
    plan_version: number | null;
    totals: PlanTotals | null;
    opportunities: OpportunitiesView;
    rotation: ShiftPlanV2["rotation"]["stats"];
  };
  simulated: true;
}

export const runtimeV2Api = {
  seek: (minute: number) => api.post<Record<string, unknown>>(`/runtime/sessions/${SID}/seek`, { minute }),
  updateSettings: (values: Partial<Record<"stow_wip_lower_min" | "stow_wip_upper_min" | "stow_wip_compliance_target" | "induct_dwell_minutes", number>>) =>
    api.patch<Record<string, unknown>>(`/runtime/sessions/${SID}/settings`, values),
  workItem: (id: string, verb: "complete" | "dismiss") =>
    api.post<WorkItem>(`/runtime/sessions/${SID}/work-items/${encodeURIComponent(id)}/${verb}`),
  packages: (params: { group: string; status?: string; column?: string; by?: "cycle" | "window" }) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v) as [string, string][]);
    return api.get<{ count: number; items: PackageListItem[] }>(`/runtime/sessions/${SID}/packages?${q.toString()}`);
  },
  report: () => api.get<ShiftReport>(`/runtime/sessions/${SID}/report`),
};

function useInvalidating<TArgs, TOut>(fn: (a: TArgs) => Promise<TOut>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ["live-state"] }) });
}

export const useSeek = () => useInvalidating(runtimeV2Api.seek);
export const useUpdateSettings = () => useInvalidating(runtimeV2Api.updateSettings);
export const useWorkItem = () =>
  useInvalidating(({ id, verb }: { id: string; verb: "complete" | "dismiss" }) => runtimeV2Api.workItem(id, verb));
export const usePackages = (params: { group: string; status?: string; column?: string; by?: "cycle" | "window" } | null) =>
  useQuery({
    queryKey: ["packages", params],
    queryFn: () => runtimeV2Api.packages(params!),
    enabled: !!params,
  });
export const useReport = () => useQuery({ queryKey: ["shift-report"], queryFn: runtimeV2Api.report });
