// Shift rotation (HANDOFF_V2 E8, S5): who goes where tomorrow, safely and
// fairly. Rotation priority, disallowed paths (heavy path on ≥2 of the last 3
// days, proposed), trained paths, last-3-days history and the recommended
// path from a min-cost assignment. Synthetic associate logins only.
import { useState } from "react";
import type { LiveState } from "../../api/runtime";
import type { RotationRow } from "../../api/runtimeV2";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { DataUpdated } from "../../components/DataUpdated";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow } from "../../components/live";
import "../../components/StatusTree.css";

const PRIORITIES = ["All", "High", "Low", "None"] as const;

export default function Rotation() {
  return (
    <div>
      <PageHeader eyebrow="People" title="Shift Rotation" badges={<DataSourceBadge kind="simulated" />}>
        Recommended process path per associate for the next shift, balancing training, repetition and strain.
        Recommendations only — a manager confirms every assignment.
      </PageHeader>
      <LiveGate>{(s) => <Body s={s} />}</LiveGate>
    </div>
  );
}

function pathLabels(s: LiveState): Record<string, string> {
  const out: Record<string, string> = {};
  const sp = s.views.shift_plan_v2;
  for (const plan of [sp.pre_shift, sp.next_day]) {
    for (const g of plan?.groups ?? []) for (const p of g.paths) out[p.path] = p.label;
  }
  return out;
}

function Body({ s }: { s: LiveState }) {
  const rot = s.views.shift_plan_v2.rotation;
  const labels = pathLabels(s);
  const name = (p: string | null) => (p ? (labels[p] ?? p.replace(/_/g, " ")) : "—");
  const [text, setText] = useState("");
  const [prio, setPrio] = useState<(typeof PRIORITIES)[number]>("All");
  const st = rot.stats;
  const rows = rot.rows.filter(
    (r) => (prio === "All" || r.rotation_priority === prio) && (!text || r.login.toLowerCase().includes(text.toLowerCase())),
  );
  const cols: Column<RotationRow>[] = [
    {
      key: "login",
      label: "Associate",
      render: (r) => (
        <>
          {r.login}
          {r.called_out && <> <Pill value="no_show" label="Called out" /></>}
          {r.vet && <> <Pill value="en_route" label="VET" /></>}
          {r.vto && <> <Pill value="neutral" label="VTO" /></>}
        </>
      ),
    },
    {
      key: "rotation_priority",
      label: "Rotation priority",
      render: (r) =>
        r.rotation_priority === "High" ? (
          <span className="prio-high">High — rotate</span>
        ) : (
          <span>{r.rotation_priority}</span>
        ),
    },
    { key: "disallowed_paths", label: "Disallowed paths", value: (r) => r.disallowed_paths.map(name).join(", ") || "—" },
    { key: "trained_paths", label: "Trained paths", value: (r) => r.trained_paths.map(name).join(", ") },
    { key: "history", label: "Last 3 days", value: (r) => r.history.map(name).join(" → ") || "—" },
    {
      key: "recommended_path",
      label: "Recommended path",
      render: (r) => (r.recommended_path ? <strong>{name(r.recommended_path)}</strong> : <span className="muted">Unassigned</span>),
      value: (r) => name(r.recommended_path),
    },
  ];
  const high = rot.rows.filter((r) => r.rotation_priority === "High").length;
  return (
    <div className="stack">
      <p className="muted" data-testid="rotation-info" style={{ margin: 0, fontSize: 13 }}>
        {rot.run
          ? `Rotation run ${st.runs ?? 1} at ${st.clock ?? "—"} · solver ${st.solver ?? "—"} · compliance ${
              st.compliance === undefined ? "—" : `${Math.round(st.compliance * 100)}%`
            } · ${st.filled ?? 0}/${st.slots ?? 0} slots filled · ${st.unfilled ?? 0} unfilled · ${st.violations ?? 0} violations`
          : "Rotation not run yet."}
      </p>
      <div className="toolbar-inline">
        <ActButton action={{ kind: "rerun_rotation" }} label="Re-run shift rotation" variant="primary" testId="rerun-rotation" />
        <span className="muted" style={{ fontSize: 12 }}>
          Rule: {rot.disallow_rule}; at most {rot.max_consecutive} consecutive days on one heavy path.
        </span>
      </div>
      {!rot.run || rot.rows.length === 0 ? (
        <Card title="Shift rotation">
          <p data-testid="rotation-empty">
            The rotation runs with tomorrow's labour plan, after dispatch once the final truckfile is in (the manager
            builds the next-day plan in the evening). Until then there is nothing to rotate — check back after close-out,
            or press "Re-run shift rotation" once the next-day plan exists.
          </p>
          <DataUpdated clock={s.snapshot.clock} />
        </Card>
      ) : (
        <>
          <StatRow>
            <Stat label="Associates" value={rot.rows.length} />
            <Stat label="High priority" value={high} sub="rotate off a repeated heavy path" />
            <Stat label="Compliance" value={st.compliance === undefined ? "—" : `${Math.round(st.compliance * 100)}%`} />
            <Stat label="Unfilled slots" value={st.unfilled ?? 0} sub={`of ${st.slots ?? 0}`} />
          </StatRow>
          <Card
            title="Rotation"
            actions={
              <div className="toolbar-inline" style={{ margin: 0 }}>
                <input
                  aria-label="Filter associates"
                  placeholder="Associate…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  style={{ width: 140 }}
                />
                <label style={{ fontSize: 12 }}>
                  Priority{" "}
                  <select aria-label="Rotation priority filter" value={prio} onChange={(e) => setPrio(e.target.value as (typeof PRIORITIES)[number])}>
                    {PRIORITIES.map((p) => (
                      <option key={p}>{p}</option>
                    ))}
                  </select>
                </label>
              </div>
            }
          >
            <DataTable
              testId="rotation-table"
              columns={cols}
              rows={rows}
              rowKey={(r) => r.login}
              maxHeight={620}
              rowClass={(r) => (r.rotation_priority === "High" ? "row-warn" : undefined)}
            />
            <DataUpdated clock={s.snapshot.clock} />
          </Card>
        </>
      )}
    </div>
  );
}
