// Associates (live, by function) and Labor (shift plan, needed vs. show
// hours, work groups with attendance, VET/VTO opportunities, shift rotation).
// Associate logins are synthetic; this is labor *planning* support for a
// simulated station — there is no individual performance management here.
import { useState } from "react";
import { type AssociateRow, type LiveState, pctv } from "../../api/runtime";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";

const ROLE_TABS = ["All", "Induct", "Stow", "Pick", "Problem solve", "High value", "Absent"] as const;
const ROLE_KEY: Record<string, string> = {
  Induct: "induct",
  Stow: "stow",
  Pick: "pick",
  "Problem solve": "problem_solve",
  "High value": "high_value",
};

export function Associates() {
  const [tab, setTab] = useState<(typeof ROLE_TABS)[number]>("All");
  return (
    <div>
      <PageHeader eyebrow="Associate" title="Associates" badges={<DataSourceBadge kind="simulated" />}>
        Who is doing what, right now: current task and picklist, time since last activity, idle time between tasks, and
        last location. Synthetic associates — no real people or performance data.
      </PageHeader>
      <Tabs tabs={ROLE_TABS} value={tab} onChange={setTab} />
      <LiveGate>{(s) => <AssocBody s={s} tab={tab} />}</LiveGate>
    </div>
  );
}

function AssocBody({ s, tab }: { s: LiveState; tab: (typeof ROLE_TABS)[number] }) {
  const a = s.views.associates;
  const rows = a.rows.filter((r) => (tab === "All" ? r.present : tab === "Absent" ? !r.present : r.present && r.role === ROLE_KEY[tab]));
  const withTask = rows.filter((r) => r.task !== "idle" && r.task !== "off_shift").length;
  const cols: Column<AssociateRow>[] = [
    { key: "login", label: "Associate", filter: true, render: (r) => <>{r.login}{r.vet && <Pill value="info" label="VET" />}</> },
    { key: "role", label: "Function", filter: true, value: (r) => r.role.replace(/_/g, " ") },
    { key: "task", label: "Current task", filter: true, render: (r) => <Pill value={r.task === "idle" ? "ready" : r.task === "off_shift" ? "neutral" : "running"} label={r.task.replace(/[_:]/g, " ")} /> },
    { key: "picklist", label: "Picklist / ref", value: (r) => r.task_ref ?? "—" },
    { key: "time_since_last_activity", label: "Since last activity", value: (r) => r.time_since_last_activity ?? "—" },
    { key: "current_task_duration", label: "Task duration", value: (r) => r.current_task_duration ?? "—" },
    { key: "idle_total", label: "Idle between tasks", value: (r) => r.idle_total ?? "—" },
    { key: "units", label: "Units", num: true },
    { key: "pph", label: "PPH", num: true, value: (r) => r.pph ?? "—" },
    { key: "location", label: "Last location", filter: true },
  ];
  return (
    <div className="stack">
      <StatRow>
        <Stat label="Total associates" value={rows.length} />
        <Stat label="With a task" value={withTask} />
        <Stat label="Without a task" value={rows.length - withTask} />
        <Stat label="Absent today" value={a.summary.absent} />
        <Stat label="VET call-ins" value={a.summary.vet} />
      </StatRow>
      <Card title={`${tab} associates`}>
        <DataTable testId="assoc-table" columns={cols} rows={rows} rowKey={(r) => r.login} maxHeight={620} />
      </Card>
    </div>
  );
}

export function Labor() {
  const [tab, setTab] = useState<"Shift plan" | "Shift rotation">("Shift plan");
  return (
    <div>
      <PageHeader eyebrow="Labor" title="Shift Plan" badges={<DataSourceBadge kind="simulated" />}>
        The labor plan for the out-for-delivery date, recomputed live from the current volume forecast (incl. revised
        ferry ETAs and unplanned volume) and actual attendance.
      </PageHeader>
      <Tabs tabs={["Shift plan", "Shift rotation"] as const} value={tab} onChange={setTab} />
      <LiveGate>{(s) => (tab === "Shift plan" ? <Plan s={s} /> : <Rotation s={s} />)}</LiveGate>
    </div>
  );
}

function Plan({ s }: { s: LiveState }) {
  const p = s.views.labor_plan;
  return (
    <div className="stack">
      <div className="grid-2">
        <Card title={`Plan — OFD ${p.ofd_date}`}>
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
              <tr>
                <td><strong>{p.cycle}</strong></td>
                <td className="num tabular">{p.total_volume.toLocaleString()}</td>
                <td className="num tabular">{p.planned_volume.toLocaleString()}</td>
                <td className="num tabular">{p.sideline_rts.toLocaleString()}</td>
                <td className="num tabular">{p.planned_rollover.toLocaleString()}</td>
              </tr>
            </tbody>
          </table>
          <table style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th className="num">Total show hrs</th>
                <th className="num">Total needed hrs</th>
                <th className="num">Planned TPH</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="num tabular">{p.total_show_hours}</td>
                <td className="num tabular">{p.total_needed_hours}</td>
                <td className="num tabular">{p.planned_tph}</td>
              </tr>
            </tbody>
          </table>
          <h3 className="page-section-title">Needed hours by function</h3>
          <StatRow>
            {Object.entries(p.needed_by_function).map(([k, v]) => (
              <Stat key={k} label={k} value={`${v}h`} />
            ))}
          </StatRow>
        </Card>
        <Card title="Work groups">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Work group</th>
                <th className="num">Attendance</th>
                <th className="num">Expected headcount</th>
                <th className="num">Expected show hours</th>
              </tr>
            </thead>
            <tbody>
              {p.work_groups.map((w) => (
                <tr key={w.work_group}>
                  <td className="tabular" style={{ whiteSpace: "nowrap" }}>{w.time}</td>
                  <td>{w.work_group}</td>
                  <td className="num tabular">{pctv(w.attendance)}</td>
                  <td className="num tabular">{w.expected_headcount}</td>
                  <td className="num tabular">{w.expected_show_hours}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <Card title="VET / VTO opportunities">
        <div className="toolbar-inline">
          <Stat label="VET opportunities" value={p.vet_opportunities} sub={`flex pool ${p.flex_remaining}`} />
          <Stat label="VTO opportunities" value={p.vto_opportunities} />
          {p.vet_opportunities > 0 && (
            <ActButton action={{ kind: "add_stowers", amount: Math.min(6, p.vet_opportunities) }} label={`Offer VET to ${Math.min(6, p.vet_opportunities)} (stow)`} variant="primary" />
          )}
        </div>
        <p className="muted" style={{ fontSize: 12 }}>
          VET call-ins arrive after a {45}-minute lead time. VTO is advisory only — the twin doesn't send people home.
        </p>
      </Card>
    </div>
  );
}

function Rotation({ s }: { s: LiveState }) {
  const rows = s.views.associates.rows.filter((r) => r.present);
  return (
    <Card title="Shift rotation (role changes during the day)">
      <DataTable
        testId="rotation-table"
        columns={[
          { key: "login", label: "Associate", filter: true },
          { key: "home_role", label: "Planned function", filter: true, value: (r) => r.home_role.replace(/_/g, " ") },
          { key: "shift_start", label: "Shift start" },
          { key: "rotation", label: "Rotation", value: (r) => r.rotation.map((x) => `${x.clock} ${x.role.replace(/_/g, " ")}`).join(" → ") },
        ]}
        rows={rows}
        rowKey={(r) => r.login}
        maxHeight={620}
      />
    </Card>
  );
}
