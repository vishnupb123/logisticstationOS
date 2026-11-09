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
import { LiveGate } from "../../components/live";

const SERIES = [
  { key: "arrived", label: "Arrive", slot: 1 },
  { key: "inducted", label: "Induct", slot: 2 },
  { key: "wip_minutes", label: "Stow WIP (min)", slot: 4 },
  { key: "stowed", label: "Stow", slot: 3 },
  { key: "picked", label: "Pick", slot: 7 },
] as const;
const BUCKETS = [
  { label: "15 min", n: 1 },
  { label: "30 min", n: 2 },
  { label: "1 hour", n: 4 },
  { label: "Cumulative", n: 0 },
];
const ROLES = ["induct", "stow", "pick", "problem_solve", "high_value"];

export function SortOverview() {
  return (
    <div>
      <PageHeader eyebrow="Sort" title="Sort Overview" badges={<DataSourceBadge kind="simulated" />}>
        Current sort process flow performance for the cycle, refreshed live.
      </PageHeader>
      <LiveGate>{(s) => <Body s={s} />}</LiveGate>
    </div>
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
  const [bucket, setBucket] = useState(2);
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
  const n = BUCKETS[bucket].n;
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
          <div className="seg" role="group" aria-label="Interval">
            {BUCKETS.map((b, i) => (
              <button key={b.label} aria-pressed={bucket === i} onClick={() => setBucket(i)}>
                {b.label}
              </button>
            ))}
          </div>
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
      </Card>
    </div>
  );
}
