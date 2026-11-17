// Sort overview (live): cycle volume, induct/stow FPH vs plan, scan and stow
// WIP compliance, the sortation-flow chart with series toggles and 15-min vs.
// cumulative mode, and the hourly actuals table (15 min / 30 min / 1 hour /
// cumulative) for receive, induct, stow, pick, units-per-labor-hour, labor.
import { Fragment, useState } from "react";
import { clockOf } from "../../api/stationOps";
import { type LiveState, pctv } from "../../api/runtime";
import { Card } from "../../components/Card";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { Kpi, KpiGrid } from "../../components/Kpi";
import { PageHeader } from "../../components/PageHeader";
import { TimeSeriesChart } from "../../components/charts/TimeSeriesChart";
import type { InductArea } from "../../api/runtimeV2";
import { type Column, DataTable } from "../../components/DataTable";
import { DataUpdated } from "../../components/DataUpdated";
import { IntervalToggle, type IntervalSize } from "../../components/IntervalToggle";
import { LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";
import "../../components/StatusTree.css";

const SERIES = [
  { key: "arrived", label: "Arrive", slot: 1 },
  { key: "inducted", label: "Induct", slot: 2 },
  { key: "wip_minutes", label: "Stow WIP (min)", slot: 4 },
  { key: "stowed", label: "Stow", slot: 3 },
  { key: "picked", label: "Pick", slot: 7 },
] as const;
const ROLES = ["induct", "stow", "pick", "problem_solve", "high_value"];

const TABS = ["Overall status", "Induct areas", "Containers"] as const;
type Tab = (typeof TABS)[number];
const INDUCT_CYCLES = ["CYCLE_1", "High_Value", "Unplanned"] as const;

export function SortOverview() {
  const [tab, setTab] = useState<Tab>("Overall status");
  return (
    <div>
      <PageHeader eyebrow="Sort" title="Sort Overview" badges={<DataSourceBadge kind="simulated" />}>
        Current sort process flow performance for the cycle, refreshed from the simulated run.
      </PageHeader>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      <LiveGate>
        {(s) =>
          tab === "Overall status" ? (
            <div className="stack">
              <InductOverallCard s={s} />
              <Body s={s} />
            </div>
          ) : tab === "Induct areas" ? (
            <InductAreas s={s} />
          ) : (
            <Containers s={s} />
          )
        }
      </LiveGate>
    </div>
  );
}

function InductOverallCard({ s }: { s: LiveState }) {
  const [cycle, setCycle] = useState<(typeof INDUCT_CYCLES)[number]>("CYCLE_1");
  const iv = s.views.induct_v2;
  const o = iv.overall[cycle];
  const rows: [string, number, boolean?][] = [
    ["Current cycle planned", o.current_cycle_planned, true],
    ["Current cycle inducted", o.current_cycle_inducted],
    ["Other / unplanned inducted", o.other_unplanned_inducted],
    ["Total inducted", o.total_inducted, true],
  ];
  const ladder: [string, number][] = [
    ["Manifested", o.manifested],
    ["Arrived", o.arrived],
    ["Marked for reprocess", o.marked_for_reprocess],
    ["Inducted (pending stow)", o.inducted],
    ["Stow buffered", o.stow_buffered],
    ["Stowed", o.stowed],
    ["Sidelined", o.sidelined],
  ];
  return (
    <Card
      title="Induct — overall status"
      actions={
        <div className="seg" role="group" aria-label="Cycle">
          {INDUCT_CYCLES.map((c) => (
            <button key={c} aria-pressed={cycle === c} onClick={() => setCycle(c)}>
              {c}
            </button>
          ))}
        </div>
      }
    >
      <StatRow>
        <Stat label="Non-con queue" value={iv.noncon_queue} sub={`${iv.noncon_total.toLocaleString()} non-conveyables today · manual handling`} />
        {rows.map(([l, v]) => (
          <Stat key={l} label={l} value={v.toLocaleString()} />
        ))}
      </StatRow>
      <div className="table-scroll">
        <table data-testid="induct-ladder" className="ladder">
          <thead>
            <tr>
              <th>Current status ({cycle})</th>
              <th className="num">Packages</th>
            </tr>
          </thead>
          <tbody>
            {ladder.map(([l, v]) => (
              <tr key={l}>
                <td>{l}</td>
                <td className="num tabular">{v.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <DataUpdated clock={s.snapshot.clock} />
    </Card>
  );
}

function InductAreas({ s }: { s: LiveState }) {
  const areas = s.views.induct_v2.areas;
  const tone = (a: InductArea) => (a.status === "Running" ? "running" : a.status === "Down" ? "down" : "planned");
  const cols: Column<InductArea>[] = [
    { key: "line", label: "Line" },
    { key: "type", label: "Type", render: (a) => (a.type === "Automated" ? "Automated line" : "Manual line") },
    {
      key: "status",
      label: "Status",
      render: (a) => (
        <>
          <Pill value={tone(a)} label={a.status} />
          {a.down_reason && <span className="muted"> {a.down_reason}</span>}
        </>
      ),
    },
    { key: "inductor", label: "Inductor", value: (a) => a.inductor ?? "—" },
    { key: "target_pph", label: "Target PPH", num: true },
    {
      key: "pph_last_hour",
      label: "PPH (last hour)",
      num: true,
      render: (a) => (
        <>
          {a.pph_last_hour.toLocaleString()}{" "}
          {a.target_pph > 0 && a.pph_last_hour < a.target_pph * 0.85 && <span className="cell-tag cell-tag--behind">below target</span>}
        </>
      ),
    },
    { key: "inducted", label: "Inducted", num: true },
    { key: "lost_hours", label: "Lost hours", num: true, render: (a) => a.lost_hours.toFixed(2) },
    { key: "stops", label: "Stops", num: true },
    { key: "no_read", label: "No-read", num: true },
    { key: "multi_read", label: "Multi-read", num: true },
    { key: "misapplied_label", label: "Misapplied label", num: true },
  ];
  const auto = areas.filter((a) => a.type === "Automated");
  const manual = areas.filter((a) => a.type === "Manual");
  return (
    <div className="stack">
      <StatRow>
        <Stat label="Automated lines" value={auto.length} sub={`${auto.reduce((x, a) => x + a.inducted, 0).toLocaleString()} inducted`} />
        <Stat label="Manual lines" value={manual.length} sub={`${manual.reduce((x, a) => x + a.inducted, 0).toLocaleString()} inducted`} />
        <Stat label="Lines down" value={areas.filter((a) => a.status === "Down").length} />
        <Stat label="Lost hours" value={areas.reduce((x, a) => x + a.lost_hours, 0).toFixed(2)} sub="belt gaps 20–120 s (documented)" />
      </StatRow>
      <Card title="Induct areas">
        <DataTable testId="induct-areas" columns={cols} rows={areas} rowKey={(a) => a.line} maxHeight={420} />
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
    </div>
  );
}

function Containers({ s }: { s: LiveState }) {
  const lh = s.views.induct_v2.containers;
  const clusters = [...new Set(lh.flatMap((l) => l.containers.flatMap((c) => Object.keys(c.clusters ?? {}))))].sort();
  return (
    <Card title="Containers by linehaul">
      <div className="table-scroll st-wrap">
        <table className="status-tree" data-testid="induct-containers">
          <thead>
            <tr>
              <th>Linehaul / container</th>
              <th>Type</th>
              <th className="num">Pending induct / total</th>
              {clusters.map((c) => (
                <th key={c} className="num">
                  Cluster {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lh.map((l) => {
              const pend = l.containers.reduce((a, c) => a + c.pending_induct, 0);
              const tot = l.containers.reduce((a, c) => a + c.total, 0);
              return (
                <Fragment key={l.linehaul}>
                  <tr className="status-tree__group">
                    <td>{l.linehaul}</td>
                    <td className="muted">{l.containers.length} containers</td>
                    <td className="num tabular">
                      {pend.toLocaleString()} / {tot.toLocaleString()}
                    </td>
                    {clusters.map((c) => (
                      <td key={c} className="num tabular">
                        {l.containers.reduce((a, x) => a + (x.clusters?.[c] ?? 0), 0).toLocaleString()}
                      </td>
                    ))}
                  </tr>
                  {l.containers.map((c) => (
                    <tr key={c.id} className="status-tree__row">
                      <td>{c.id}</td>
                      <td>{c.type === "GAYLORD" ? "Gaylord" : "Pallet"}</td>
                      <td className="num tabular">
                        {c.pending_induct} / {c.total}
                        {c.unloaded === false && <span className="cell-tag">not unloaded</span>}
                      </td>
                      {clusters.map((k) => (
                        <td key={k} className="num tabular">
                          {(c.clusters?.[k] ?? 0).toLocaleString()}
                        </td>
                      ))}
                    </tr>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <DataUpdated clock={s.snapshot.clock} />
    </Card>
  );
}

function cumulative(v: number[]) {
  let acc = 0;
  return v.map((x) => (acc += x));
}

function Body({ s }: { s: LiveState }) {
  const snap = s.snapshot;
  const m = snap.metrics;
  const [on, setOn] = useState<Record<string, boolean>>({ inducted: true, stowed: true, arrived: true });
  const [cum, setCum] = useState(false);
  const [n, setN] = useState<IntervalSize>(2);
  const x = snap.series.minute ?? [];
  const chartSeries = SERIES.filter((d) => on[d.key]).map((d) => {
    const raw = snap.series[d.key] ?? [];
    return {
      key: d.key,
      label: d.label,
      color: `var(--series-${d.slot})`,
      values: cum && d.key !== "wip_minutes" ? cumulative(raw) : raw,
    };
  });

  // hourly table
  const cols: { from: number; to: number }[] = [];
  if (n === 0) {
    if (x.length) cols.push({ from: 0, to: x.length });
  } else {
    const start = x.findIndex((v) => v >= 120);
    for (let i = Math.max(0, start); i < x.length; i += n) cols.push({ from: i, to: Math.min(x.length, i + n) });
  }
  const sum = (k: string, c: { from: number; to: number }) =>
    (snap.series[k] ?? []).slice(c.from, c.to).reduce((a, b) => a + b, 0);
  const labor = (c: { from: number; to: number }) => ROLES.reduce((a, r) => a + sum(`labor_${r}`, c), 0);
  const rows: { label: string; group?: string; fn: (c: { from: number; to: number }) => string }[] = [
    { label: "Receive actuals", group: "Inbound", fn: (c) => sum("arrived", c).toLocaleString() },
    { label: "Induct actuals", fn: (c) => sum("inducted", c).toLocaleString() },
    { label: "Stow actuals", fn: (c) => sum("stowed", c).toLocaleString() },
    { label: "Pick actuals", group: "Outbound", fn: (c) => sum("picked", c).toLocaleString() },
    {
      label: "Units / labor hour",
      group: "Station",
      fn: (c) => {
        const h = labor(c);
        return h ? Math.round((sum("inducted", c) + sum("stowed", c) + sum("picked", c)) / h).toString() : "—";
      },
    },
    { label: "Labor actuals (h)", fn: (c) => labor(c).toFixed(1) },
  ];
  const colLabel = (c: { from: number; to: number }) =>
    n === 0 ? "Cumulative" : `${clockOf(x[c.from])}–${clockOf((x[c.to - 1] ?? x[c.from]) + 15)}`;

  return (
    <div className="stack">
      <KpiGrid>
        <Kpi label="Total volume" value={snap.inbound.arrived_volume.toLocaleString()} caption={`arrived · ${snap.induct.inducted.toLocaleString()} inducted`} />
        <Kpi label="Induct FPH" value={snap.induct.fph_last_hour.toLocaleString()} caption={`target ${(m.induct_fph.target ?? 0).toLocaleString()}`} />
        <Kpi label="Stow PPH / stower" value={m.stow_pph.value === null ? "—" : Math.round(m.stow_pph.value)} caption={`target ${m.stow_pph.target}`} />
        <Kpi label="Scan compliance" value={pctv(m.scan_compliance.value, 2)} caption={`${snap.induct.no_reads} no-reads`} />
        <Kpi label="Est. stow WIP compliance" value={pctv(m.stow_wip_compliance.value)} caption={`target ${pctv(m.stow_wip_compliance.target, 0)}`} />
        <Kpi label="Stow WIP" value={`${snap.stow.wip_minutes.toFixed(1)} min`} caption={`target ${snap.stow.wip_target_min}/${snap.stow.wip_target_max}`} />
      </KpiGrid>
      <Card
        title="Sortation flow"
        actions={
          <div className="toolbar-inline" style={{ margin: 0 }}>
            {SERIES.map((d) => (
              <label key={d.key} style={{ fontSize: 12, display: "inline-flex", gap: 4 }}>
                <input type="checkbox" checked={!!on[d.key]} onChange={(e) => setOn((o) => ({ ...o, [d.key]: e.target.checked }))} />
                {d.label}
              </label>
            ))}
            <div className="seg">
              <button aria-pressed={!cum} onClick={() => setCum(false)}>15 min</button>
              <button aria-pressed={cum} onClick={() => setCum(true)}>Cumulative</button>
            </div>
          </div>
        }
      >
        <TimeSeriesChart ariaLabel="Sortation flow" x={x} xFormatter={clockOf} series={chartSeries} height={260} />
      </Card>
      <Card
        title="Actuals by interval"
        actions={
          <IntervalToggle value={n} onChange={setN} />
        }
      >
        <div className="table-scroll">
          <table data-testid="sort-hourly">
            <thead>
              <tr>
                <th>All cycles</th>
                {cols.map((c) => (
                  <th key={c.from} className="num">
                    {colLabel(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <Fragment key={r.label}>
                  {r.group && (
                    <tr key={`g-${r.group}`} className="recv-head">
                      <td colSpan={cols.length + 1}>
                        <span className="muted">{r.group}</span>
                      </td>
                    </tr>
                  )}
                  <tr key={r.label}>
                    <td>
                      <strong>{r.label}</strong>
                    </td>
                    {cols.map((c) => (
                      <td key={c.from} className="num tabular">
                        {r.fn(c)}
                      </td>
                    ))}
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        <DataUpdated clock={snap.clock} />
      </Card>
    </div>
  );
}
