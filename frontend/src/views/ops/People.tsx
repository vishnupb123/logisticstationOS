// Associates (HANDOFF_V2 E9: performance by path — induct / stow / pick,
// team aggregates by default, per-associate rows only behind a claimed
// manager-role toggle) and the Shift Plan (E6/E7: next-day and pre-shift
// labour plans, work groups, the hourly path matrix, VET/VTO opportunities
// with sign-up windows and recommendations). Associate logins are synthetic.
import { Fragment, useState } from "react";
import { type AssociateRow, type LiveState, pctv } from "../../api/runtime";
import type { InductAssoc, LaborPlanV2, Opportunity, PickAssoc, StowAssoc } from "../../api/runtimeV2";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { DataUpdated } from "../../components/DataUpdated";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";
import "../../components/StatusTree.css";

// ---------------------------------------------------------------- Associates

const ASSOC_TABS = ["Induct", "Stow", "Pick", "Floor (current task)"] as const;
type AssocTab = (typeof ASSOC_TABS)[number];

export function Associates() {
  const [tab, setTab] = useState<AssocTab>("Induct");
  const [individual, setIndividual] = useState(false);
  return (
    <div>
      <PageHeader eyebrow="Associate" title="Associates" badges={<DataSourceBadge kind="simulated" />}>
        Performance by process path for coaching and balancing — team aggregates by default. Synthetic associates; no
        real people or performance data.
      </PageHeader>
      <Tabs tabs={ASSOC_TABS} value={tab} onChange={setTab} />
      <LiveGate>
        {(s) => (
          <div className="stack">
            {tab !== "Floor (current task)" && (
              <div className="toolbar-inline">
                <label style={{ fontSize: 13, display: "inline-flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={individual} onChange={(e) => setIndividual(e.target.checked)} data-testid="show-individual" />
                  Show individual rows (manager role)
                </label>
                <span className="muted" style={{ fontSize: 12 }}>
                  The role is claimed, not authenticated (dev mode).
                </span>
              </div>
            )}
            {tab === "Induct" ? (
              <InductPerf s={s} individual={individual} />
            ) : tab === "Stow" ? (
              <StowPerf s={s} individual={individual} />
            ) : tab === "Pick" ? (
              <PickPerf s={s} individual={individual} />
            ) : (
              <Floor s={s} />
            )}
            {tab !== "Floor (current task)" && (
              <p className="muted" style={{ fontSize: 12 }} data-testid="governance-note">
                {s.views.associate_performance.governance}
              </p>
            )}
          </div>
        )}
      </LiveGate>
    </div>
  );
}

const sumOf = <T,>(rows: T[], f: (r: T) => number | null | undefined) => rows.reduce((a, r) => a + (f(r) ?? 0), 0);
const avgOf = <T,>(rows: T[], f: (r: T) => number | null | undefined) => {
  const v = rows.map(f).filter((x): x is number => x !== null && x !== undefined);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
};
const r0 = (v: number | null) => (v === null ? "—" : Math.round(v).toLocaleString());
const r1 = (v: number | null) => (v === null ? "—" : v.toFixed(1));

function groupBy<T>(rows: T[], key: (r: T) => string): [string, T[]][] {
  const m = new Map<string, T[]>();
  for (const r of rows) m.set(key(r), [...(m.get(key(r)) ?? []), r]);
  return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

interface Agg {
  group: string;
  associates: number;
  active: number;
  hours: number;
  packages: number;
  pph: number | null;
  [k: string]: string | number | null;
}

const AGG_COLS: Column<Agg>[] = [
  { key: "group", label: "Team" },
  { key: "associates", label: "Associates", num: true },
  { key: "active", label: "Active now", num: true },
  { key: "hours", label: "Hours", num: true, render: (a) => a.hours.toFixed(1) },
  { key: "packages", label: "Packages", num: true, render: (a) => a.packages.toLocaleString() },
  { key: "pph", label: "PPH (team)", num: true, render: (a) => r0(a.pph) },
];

function aggregate<T extends { hours: number; total_packages: number; active: boolean }>(group: string, rows: T[]): Agg {
  const hours = sumOf(rows, (r) => r.hours);
  const packages = sumOf(rows, (r) => r.total_packages);
  return { group, associates: rows.length, active: rows.filter((r) => r.active).length, hours, packages, pph: hours ? packages / hours : null };
}

function InductPerf({ s, individual }: { s: LiveState; individual: boolean }) {
  const rows = s.views.associate_performance.induct;
  const agg = [...groupBy(rows, (r) => r.location).map(([g, rs]) => aggregate(g, rs)), aggregate("All induct", rows)];
  const cols: Column<InductAssoc>[] = [
    { key: "associate", label: "Associate", filter: true },
    { key: "pph", label: "PPH", num: true, value: (r) => r.pph ?? "—" },
    { key: "hours", label: "Hours", num: true },
    { key: "total_packages", label: "Packages", num: true },
    { key: "active", label: "Active", render: (r) => <Pill value={r.active ? "running" : "neutral"} label={r.active ? "Active" : "Inactive"} /> },
    { key: "location", label: "Location", filter: true },
  ];
  return (
    <>
      <StatRow>
        <Stat label="Inductors" value={rows.length} sub={`${rows.filter((r) => r.active).length} active`} />
        <Stat label="Packages inducted" value={sumOf(rows, (r) => r.total_packages).toLocaleString()} />
        <Stat label="Team PPH" value={r0(agg[agg.length - 1].pph)} />
      </StatRow>
      <Card title={individual ? "Induct — individual rows" : "Induct — team aggregates by line"}>
        {individual ? (
          <DataTable testId="assoc-table" columns={cols} rows={rows} rowKey={(r) => r.associate} maxHeight={520} />
        ) : (
          <DataTable testId="assoc-table" columns={AGG_COLS} rows={agg} rowKey={(r) => r.group} maxHeight={520} empty="No inductors on the floor." />
        )}
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
    </>
  );
}

function StowPerf({ s, individual }: { s: LiveState; individual: boolean }) {
  const rows = s.views.associate_performance.stow;
  const mk = (g: string, rs: StowAssoc[]): Agg => {
    const a = aggregate(g, rs);
    const fsaf = sumOf(rs, (r) => r.fsaf);
    return {
      ...a,
      fsaf,
      fsaf_dpmo: a.packages ? Math.round((fsaf / a.packages) * 1e6) : null,
      stow_scan_to_ps: sumOf(rs, (r) => r.stow_scan_to_ps),
      spot_checks: sumOf(rs, (r) => r.spot_checks),
    };
  };
  const agg = [...groupBy(rows, (r) => (r.cluster ? `Cluster ${r.cluster}` : "No cluster")).map(([g, rs]) => mk(g, rs)), mk("All stow", rows)];
  const aggCols: Column<Agg>[] = [
    ...AGG_COLS,
    { key: "fsaf", label: "FSAF", num: true },
    { key: "fsaf_dpmo", label: "FSAF DPMO", num: true, value: (a) => a.fsaf_dpmo ?? "—" },
    { key: "stow_scan_to_ps", label: "Stow scan → PS", num: true },
    { key: "spot_checks", label: "Spot checks", num: true },
  ];
  const cols: Column<StowAssoc>[] = [
    { key: "associate", label: "Associate", filter: true },
    { key: "pph", label: "PPH", num: true, value: (r) => r.pph ?? "—" },
    { key: "hours", label: "Hours", num: true },
    { key: "total_packages", label: "Packages", num: true },
    { key: "fsaf", label: "FSAF", num: true },
    { key: "fsaf_dpmo", label: "FSAF DPMO", num: true, value: (r) => r.fsaf_dpmo ?? "—" },
    { key: "stow_scan_to_ps", label: "Stow scan → PS", num: true },
    { key: "spot_checks", label: "Spot checks", num: true },
    { key: "spot_check_dpmo", label: "Spot-check DPMO", num: true, value: (r) => r.spot_check_dpmo ?? "—" },
    { key: "active", label: "Active", render: (r) => <Pill value={r.active ? "running" : "neutral"} label={r.active ? "Active" : "Inactive"} /> },
    { key: "last_location", label: "Last location", filter: true },
    { key: "cluster", label: "Cluster", filter: true, value: (r) => r.cluster ?? "—" },
  ];
  const total = agg[agg.length - 1];
  return (
    <>
      <StatRow>
        <Stat label="Stowers" value={rows.length} sub={`${rows.filter((r) => r.active).length} active`} />
        <Stat label="Packages stowed" value={total.packages.toLocaleString()} />
        <Stat label="Team PPH" value={r0(total.pph)} />
        <Stat label="FSAF DPMO (team)" value={total.fsaf_dpmo ?? "—"} sub="first sort attempt failures per million" />
      </StatRow>
      <Card title={individual ? "Stow — individual rows" : "Stow — team aggregates by cluster"}>
        {individual ? (
          <DataTable testId="assoc-table" columns={cols} rows={rows} rowKey={(r) => r.associate} maxHeight={520} />
        ) : (
          <DataTable testId="assoc-table" columns={aggCols} rows={agg} rowKey={(r) => r.group} maxHeight={520} empty="No stowers on the floor." />
        )}
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
    </>
  );
}

function PickPerf({ s, individual }: { s: LiveState; individual: boolean }) {
  const ap = s.views.associate_performance;
  const rows = ap.pick;
  const ps = ap.pick_summary;
  const agg = groupBy(rows, (r) => (r.picklist_assigned ? "With picklist" : "Without picklist")).map(([g, rs]) => ({
    group: g,
    associates: rs.length,
    hours: sumOf(rs, (r) => r.hours),
    units: sumOf(rs, (r) => r.units),
    since: avgOf(rs, (r) => r.time_since_last_activity_min),
    idle: avgOf(rs, (r) => r.idle_between_picklists_min),
  }));
  const cols: Column<PickAssoc>[] = [
    { key: "associate", label: "Associate", filter: true },
    { key: "picklist_assigned", label: "Picklist assigned", render: (r) => <Pill value={r.picklist_assigned ? "running" : "ready"} label={r.picklist_assigned ? "Yes" : "No"} /> },
    { key: "time_since_last_activity_min", label: "Since last activity (min)", num: true, value: (r) => (r.time_since_last_activity_min === null ? "—" : r.time_since_last_activity_min.toFixed(0)) },
    { key: "picklist_id", label: "Picklist ID", value: (r) => r.picklist_id ?? "—" },
    { key: "current_picklist_minutes", label: "Current picklist (min)", num: true, value: (r) => (r.current_picklist_minutes === null ? "—" : r.current_picklist_minutes.toFixed(0)) },
    { key: "idle_between_picklists_min", label: "Idle between picklists (min)", num: true, value: (r) => r.idle_between_picklists_min.toFixed(0) },
    { key: "last_location", label: "Last staging location", filter: true },
    { key: "units", label: "Units", num: true },
  ];
  return (
    <>
      <StatRow>
        <Stat label="Total pickers" value={ps.total} />
        <Stat label="With picklist" value={ps.with_picklist} />
        <Stat label="Without picklist" value={ps.without_picklist} />
      </StatRow>
      <Card title={individual ? "Pick — individual rows" : "Pick — team aggregates"}>
        {rows.length === 0 ? (
          <p className="muted" data-testid="assoc-table">
            Pick hasn't started; pickers appear here once picklists are released.
          </p>
        ) : individual ? (
          <DataTable testId="assoc-table" columns={cols} rows={rows} rowKey={(r) => r.associate} maxHeight={520} />
        ) : (
          <DataTable
            testId="assoc-table"
            columns={[
              { key: "group", label: "Team" },
              { key: "associates", label: "Associates", num: true },
              { key: "hours", label: "Hours", num: true, render: (a) => a.hours.toFixed(1) },
              { key: "units", label: "Units", num: true, render: (a) => a.units.toLocaleString() },
              { key: "since", label: "Avg since last activity (min)", num: true, render: (a) => r1(a.since) },
              { key: "idle", label: "Avg idle between picklists (min)", num: true, render: (a) => r1(a.idle) },
            ]}
            rows={agg}
            rowKey={(r) => r.group}
          />
        )}
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
    </>
  );
}

function Floor({ s }: { s: LiveState }) {
  const a = s.views.associates;
  const rows = a.rows.filter((r) => r.present);
  const withTask = rows.filter((r) => r.task !== "idle" && r.task !== "off_shift").length;
  const cols: Column<AssociateRow>[] = [
    { key: "login", label: "Associate", filter: true, render: (r) => <>{r.login}{r.vet && <Pill value="info" label="VET" />}</> },
    { key: "role", label: "Function", filter: true, value: (r) => r.role.replace(/_/g, " ") },
    { key: "task", label: "Current task", filter: true, render: (r) => <Pill value={r.task === "idle" ? "ready" : r.task === "off_shift" ? "neutral" : "running"} label={r.task.replace(/[_:]/g, " ")} /> },
    { key: "picklist", label: "Picklist / ref", value: (r) => r.task_ref ?? "—" },
    { key: "time_since_last_activity", label: "Since last activity", value: (r) => r.time_since_last_activity ?? "—" },
    { key: "current_task_duration", label: "Task duration", value: (r) => r.current_task_duration ?? "—" },
    { key: "idle_total", label: "Idle between tasks", value: (r) => r.idle_total ?? "—" },
    { key: "location", label: "Last location", filter: true },
  ];
  return (
    <div className="stack">
      <StatRow>
        <Stat label="Present" value={rows.length} />
        <Stat label="With a task" value={withTask} />
        <Stat label="Without a task" value={rows.length - withTask} />
        <Stat label="Absent today" value={a.summary.absent} />
        <Stat label="VET call-ins" value={a.summary.vet} />
      </StatRow>
      <Card title="Who is doing what">
        <DataTable testId="assoc-floor" columns={cols} rows={rows} rowKey={(r) => r.login} maxHeight={620} />
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- Shift plan

type PlanTab = "Next Day" | "Pre-Shift";

export function Labor() {
  return (
    <div>
      <PageHeader eyebrow="Labor" title="Shift Plan" badges={<DataSourceBadge kind="simulated" />}>
        Labour plans for the out-for-delivery date: the next-day plan built from tomorrow's final truckfile, and the
        pre-shift plan re-run at shift start with actual call-outs. Rates and attendance are proposed.
      </PageHeader>
      <LiveGate>{(s) => <PlanBody s={s} />}</LiveGate>
    </div>
  );
}

function PlanBody({ s }: { s: LiveState }) {
  const sp = s.views.shift_plan_v2;
  const [tab, setTab] = useState<PlanTab>(sp.next_day ? "Next Day" : "Pre-Shift");
  const plan = tab === "Next Day" ? sp.next_day : sp.pre_shift;
  return (
    <div className="stack">
      <Tabs tabs={["Next Day", "Pre-Shift"] as const} value={tab} onChange={setTab} />
      <p className="muted" data-testid="plan-status" style={{ margin: 0, fontSize: 13 }}>
        {tab === "Next Day"
          ? `${sp.next_day_label}${sp.next_day_version ? ` · plan version ${sp.next_day_version}` : ""} · OFD ${sp.ofd_date}`
          : `Pre-shift plan for today, re-run with actual call-outs · ${plan?.provenance ?? ""}`}
      </p>
      {plan ? (
        <PlanView s={s} plan={plan} nextDay={tab === "Next Day"} />
      ) : (
        <Card title="Next day plan">
          <p data-testid="next-day-empty">
            {sp.next_day_label}. The next-day plan is built from tomorrow's final truckfile after dispatch; switch to
            Pre-Shift for today's plan.
          </p>
        </Card>
      )}
      <Opportunities s={s} />
    </div>
  );
}

function PlanView({ s, plan, nextDay }: { s: LiveState; plan: LaborPlanV2; nextDay: boolean }) {
  const t = plan.totals;
  return (
    <>
      <div className="grid-2">
        <Card title="Cycles">
          <div className="table-scroll">
            <table data-testid="labor-plan">
              <thead>
                <tr>
                  <th>Cycle</th>
                  <th className="num">Total volume</th>
                  <th className="num">Planned volume</th>
                  <th className="num">Sideline / RTS</th>
                  <th className="num">Planned rollover</th>
                </tr>
              </thead>
              <tbody>
                {plan.cycles.map((c) => (
                  <tr key={c.cycle}>
                    <td>
                      <strong>{c.cycle}</strong>
                    </td>
                    <td className="num tabular">{c.total_volume.toLocaleString()}</td>
                    <td className="num tabular">{c.planned_volume.toLocaleString()}</td>
                    <td className="num tabular">{c.sideline_rts.toLocaleString()}</td>
                    <td className="num tabular">{c.planned_rollover.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Totals">
          <StatRow>
            <Stat label="Total show hrs" value={t.show_hours.toLocaleString()} />
            <Stat
              label="Total needed hrs"
              value={t.needed_hours.toLocaleString()}
              sub={t.show_hours >= t.needed_hours ? `${(t.show_hours - t.needed_hours).toFixed(1)} h surplus` : `${(t.needed_hours - t.show_hours).toFixed(1)} h short`}
            />
            <Stat label="Planned TPH (with indirect)" value={t.tph_with_indirect ?? "—"} sub={`indirect allowance ${(t.indirect_allowance * 100).toFixed(0)}% (proposed)`} />
            <Stat label="Planned TPH (without indirect)" value={t.tph_without_indirect ?? "—"} />
          </StatRow>
        </Card>
      </div>
      <Card title="Work groups">
        <DataTable
          testId="work-groups"
          columns={[
            { key: "window", label: "Time" },
            { key: "name", label: "Work group" },
            { key: "attendance", label: "Attendance", num: true, render: (w) => pctv(w.attendance, 0) },
            { key: "scheduled", label: "Scheduled", num: true },
            { key: "expected_headcount", label: "Expected headcount", num: true },
            { key: "expected_show_hours", label: "Expected show hours", num: true },
            { key: "needed_peak", label: "Needed (peak HC in window)", num: true },
          ]}
          rows={plan.work_groups}
          rowKey={(w) => w.name}
          maxHeight={420}
        />
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
      <HourlyGrid s={s} plan={plan} title={nextDay ? "Next day planned — hourly" : "Pre-shift planned — hourly"} />
    </>
  );
}

function HourlyGrid({ s, plan, title }: { s: LiveState; plan: LaborPlanV2; title: string }) {
  const [view, setView] = useState<"hc" | "hours">("hc");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const fmt = (v: number) => (v === 0 ? "" : v.toFixed(1));
  const tot = (v: number[]) => v.reduce((a, b) => a + b, 0);
  const peak = (v: number[]) => (v.length ? Math.max(...v) : 0);
  // Headcount = people on the path in that hour; hours = HC × 1 h columns.
  const lastCol = (v: number[]) => (view === "hc" ? peak(v) : tot(v));
  return (
    <Card
      title={title}
      actions={
        <div className="seg" role="group" aria-label="View by">
          <button aria-pressed={view === "hc"} onClick={() => setView("hc")}>
            Headcount
          </button>
          <button aria-pressed={view === "hours"} onClick={() => setView("hours")}>
            Hours
          </button>
        </div>
      }
    >
      <div className="v2-grid-wrap">
        <table className="v2-grid" data-testid="plan-grid">
          <thead>
            <tr>
              <th>{view === "hc" ? "Headcount" : "Hours"}</th>
              {plan.hours.map((h) => (
                <th key={h} className="num">
                  {h}
                </th>
              ))}
              <th className="num">{view === "hc" ? "Peak" : "Total"}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>Total volume</strong>
              </td>
              {plan.total_volume.map((v, i) => (
                <td key={i} className="num tabular">
                  {v ? v.toLocaleString() : ""}
                </td>
              ))}
              <td className="num tabular">{tot(plan.total_volume).toLocaleString()}</td>
            </tr>
            {plan.groups.map((g) => {
              const isOpen = !!open[g.group];
              return (
                <Fragment key={g.group}>
                  <tr className="status-tree__group">
                    <td>
                      <button className="status-tree__toggle" aria-expanded={isOpen} onClick={() => setOpen((o) => ({ ...o, [g.group]: !isOpen }))}>
                        <span aria-hidden>{isOpen ? "▾" : "▸"}</span> {g.group}
                      </button>
                    </td>
                    {g.hc.map((v, i) => (
                      <td key={i} className="num tabular">
                        {fmt(v)}
                      </td>
                    ))}
                    <td className="num tabular">{lastCol(g.hc).toFixed(1)}</td>
                  </tr>
                  {isOpen &&
                    g.paths.map((p) => (
                      <tr key={p.path} className="v2-grid__sub">
                        <td>{p.label}</td>
                        {p.hc.map((v, i) => (
                          <td key={i} className="num tabular">
                            {fmt(v)}
                          </td>
                        ))}
                        <td className="num tabular">{view === "hc" ? peak(p.hc).toFixed(1) : p.hours.toFixed(1)}</td>
                      </tr>
                    ))}
                </Fragment>
              );
            })}
            <tr className="v2-grid__section">
              <td>Staffing</td>
              <td colSpan={plan.hours.length + 1} />
            </tr>
            {(
              [
                ["Needed", plan.needed_by_hour],
                ["Available", plan.available_by_hour],
              ] as const
            ).map(([l, v]) => (
              <tr key={l}>
                <td>{l}</td>
                {v.map((x, i) => (
                  <td key={i} className="num tabular">
                    {fmt(x)}
                  </td>
                ))}
                <td className="num tabular">{lastCol([...v]).toFixed(1)}</td>
              </tr>
            ))}
            <tr>
              <td>Gap (needed − available)</td>
              {plan.gap_by_hour.map((x, i) => (
                <td key={i} className={`num tabular ${x >= 1 ? "cell--behind" : ""}`}>
                  {x === 0 ? "" : x.toFixed(1)}
                  {x >= 1 && <span className="cell-tag cell-tag--behind">short</span>}
                  {x <= -1 && <span className="cell-tag">surplus</span>}
                </td>
              ))}
              <td />
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        Fractional headcount per path per hour = volume through the path ÷ path rate. Provenance: {plan.provenance}.
      </p>
      <DataUpdated clock={s.snapshot.clock} />
    </Card>
  );
}

function Opportunities({ s }: { s: LiveState }) {
  const o = s.views.shift_plan_v2.opportunities;
  const anyOpen = o.opportunities.some((x) => x.status === "open");
  const cols: Column<Opportunity>[] = [
    { key: "type", label: "Type", render: (x) => <strong>{x.type}</strong> },
    { key: "time_frame", label: "Time frame", value: (x) => `${x.frame} (${x.time_frame})` },
    {
      key: "window",
      label: "Sign-up window",
      render: (x) =>
        x.window === "Open" ? (
          <>
            <Pill value="running" label="Open" /> <span className="muted">closes {x.window_close_clock}</span>
          </>
        ) : (
          <>
            <Pill value="neutral" label="Closed" /> <span className="muted">{x.closed_clock ? `at ${x.closed_clock}` : ""}{x.closed_reason ? ` · ${x.closed_reason}` : ""}</span>
          </>
        ),
    },
    { key: "headcount", label: "Posted HC", num: true },
    { key: "submitted", label: "Submitted", num: true },
    { key: "accepted", label: "Accepted", num: true },
    { key: "source", label: "Source", value: (x) => `${x.source} · ${x.posted_clock}` },
  ];
  return (
    <>
      <Card
        title="Active VTO/VET opportunities"
        actions={anyOpen ? <ActButton action={{ kind: "close_window" }} label="Close open windows" testId="close-windows" /> : undefined}
      >
        <DataTable
          testId="opportunities"
          columns={cols}
          rows={o.opportunities}
          rowKey={(x) => x.id}
          maxHeight={320}
          empty="No opportunities posted yet. Post one from the recommendations below once the next-day plan shows a gap."
        />
        <p className="muted" style={{ fontSize: 12 }}>
          Associates submit while the sign-up window is open ({o.signup_window_minutes} min); the station accepts up to need
          (rule: {o.rule.replace(/_/g, " ")}).
        </p>
      </Card>
      <Card title="Recommendations (assume no more acceptance of submitted opportunities)">
        {o.recommendations.length === 0 ? (
          <p className="muted" data-testid="recommendations-empty">
            No more opportunities recommended — every work-group frame is within one headcount of need.
          </p>
        ) : (
          <div className="table-scroll">
            <table data-testid="recommendations">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Time frame</th>
                  <th className="num"># of opportunities (HC)</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {o.recommendations.map((r) => (
                  <tr key={`${r.type}-${r.frame}`}>
                    <td>
                      <strong>{r.type}</strong>
                    </td>
                    <td>
                      {r.frame} ({r.time_frame})
                    </td>
                    <td className="num tabular">{r.headcount}</td>
                    <td>
                      <ActButton
                        action={{ kind: "post_opportunity", target: r.type, amount: Math.min(12, r.headcount), params: { frame: r.frame } }}
                        label="Post"
                        variant="primary"
                        testId={`post-${r.type}-${r.frame}`}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
    </>
  );
}
