// Plan vs. actual (HANDOFF_V2 E9, S13): an interval grid over the day —
// receive, induct (automation / manual), stow, pick, PPH vs. target, and
// labour hours by group — with the shared 15 / 30 / 60 / cumulative toggle.
// Cells are shaded only with status tokens and always carry a text label.
import { Fragment, type ReactNode, useState } from "react";
import type { LiveState } from "../../api/runtime";
import type { PvaInterval } from "../../api/runtimeV2";
import { Card } from "../../components/Card";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { DataUpdated } from "../../components/DataUpdated";
import { IntervalToggle, type IntervalSize } from "../../components/IntervalToggle";
import { PageHeader } from "../../components/PageHeader";
import { LiveGate, Stat, StatRow } from "../../components/live";
import "../../components/StatusTree.css";

type NumKey = {
  [K in keyof PvaInterval]: PvaInterval[K] extends number | null ? K : never;
}[keyof PvaInterval];

interface Col {
  label: string;
  rows: PvaInterval[]; // intervals aggregated into this column
  hours: number;
  future: boolean; // no actuals yet
}

interface GridRow {
  label: string;
  sub?: boolean;
  /** value for the column, null = not yet known */
  value: (c: Col) => number | null;
  /** planned value to compare against (actual rows only) */
  plan?: (c: Col) => number | null;
  /** higher is better (default) */
  digits?: number;
  /** lower-is-fine rows (labour hours) aren't graded */
  graded?: boolean;
  /** what the comparison is against, for the cell's text label */
  of?: string;
}

function sum(rows: PvaInterval[], k: NumKey): number | null {
  let acc = 0;
  let any = false;
  for (const r of rows) {
    const v = r[k] as number | null;
    if (v !== null && v !== undefined) {
      acc += v;
      any = true;
    }
  }
  return any ? acc : null;
}

function labor(rows: PvaInterval[], g: string): number | null {
  let acc = 0;
  let any = false;
  for (const r of rows) {
    const v = r.labor?.[g];
    if (v !== null && v !== undefined) {
      acc += v;
      any = true;
    }
  }
  return any ? acc : null;
}

function grade(actual: number | null, plan: number | null, of = "plan"): { cls: string; tag: string; tone: string } | null {
  if (actual === null || plan === null || plan <= 0) return null;
  const r = actual / plan;
  const tag = `${Math.round(r * 100)}% of ${of}`;
  if (r < 0.7) return { cls: "cell--far", tag, tone: "far" };
  if (r < 0.9) return { cls: "cell--behind", tag, tone: "behind" };
  return { cls: "", tag, tone: "ok" };
}

function buildCols(intervals: PvaInterval[], n: IntervalSize, nowMin: number): Col[] {
  const has = (r: PvaInterval) => r.start < nowMin;
  if (n === 0) {
    // cumulative: running totals at the end of each hour
    const out: Col[] = [];
    for (let i = 4; i <= intervals.length + 3; i += 4) {
      const rows = intervals.slice(0, Math.min(i, intervals.length));
      if (!rows.length) break;
      const last = rows[rows.length - 1];
      out.push({
        label: `to ${last.label.split("–")[1] ?? last.label}`,
        rows,
        hours: rows.length / 4,
        future: !has(intervals[Math.max(0, i - 4)]),
      });
      if (i >= intervals.length) break;
    }
    return out;
  }
  const out: Col[] = [];
  for (let i = 0; i < intervals.length; i += n) {
    const rows = intervals.slice(i, i + n);
    const first = rows[0].label.split("–")[0];
    const last = rows[rows.length - 1].label.split("–")[1] ?? "";
    out.push({ label: `${first}–${last}`, rows, hours: rows.length / 4, future: !has(rows[0]) });
  }
  return out;
}

export default function PlanVsActual() {
  return (
    <div>
      <PageHeader eyebrow="Operate" title="Plan vs. Actual" badges={<DataSourceBadge kind="simulated" />}>
        Planned vs. actual volume, rate and labour hours per interval for the simulated day. Actuals fill in as the
        simulated clock advances.
      </PageHeader>
      <LiveGate>{(s) => <Body s={s} />}</LiveGate>
    </div>
  );
}

function Body({ s }: { s: LiveState }) {
  const pva = s.views.plan_vs_actual;
  const [n, setN] = useState<IntervalSize>(4);
  const nowMin = (s.snapshot as { minute?: number }).minute ?? clockToMin(s.snapshot.clock);
  const cols = buildCols(pva.intervals, n, nowMin);
  const actual = (k: NumKey) => (c: Col) => (c.future ? null : sum(c.rows, k));
  const planned = (k: NumKey) => (c: Col) => sum(c.rows, k);
  const perHour = (k: NumKey) => (c: Col) => {
    if (c.future) return null;
    const v = sum(c.rows, k);
    return v === null ? null : v / c.hours;
  };
  const stowPph = (c: Col) => {
    if (c.future) return null;
    const v = sum(c.rows, "stow_actual");
    const sh = c.rows.reduce((a, r) => a + (r.stowers ?? 0) * 0.25, 0);
    return v === null || sh <= 0 ? null : v / sh;
  };
  const laborTotal = (c: Col) => {
    if (c.future) return null;
    let acc = 0;
    for (const g of pva.labor_groups) acc += labor(c.rows, g) ?? 0;
    return acc;
  };
  const tph = (c: Col) => {
    const h = laborTotal(c);
    if (!h) return null;
    return ((sum(c.rows, "induct_actual") ?? 0) + (sum(c.rows, "stow_actual") ?? 0) + (sum(c.rows, "pick_actual") ?? 0)) / h;
  };
  const sections: { title: string; rows: GridRow[] }[] = [
    {
      title: "Inbound",
      rows: [
        { label: "Receive planned", value: planned("receive_planned") },
        { label: "Receive actual", value: actual("receive_actual"), plan: planned("receive_planned"), graded: true },
        { label: "Induct planned", value: planned("induct_planned") },
        { label: "Induct actual", value: actual("induct_actual"), plan: planned("induct_planned"), graded: true },
        { label: "Automation planned", sub: true, value: planned("induct_auto_planned") },
        { label: "Automation actual", sub: true, value: actual("induct_auto_actual"), plan: planned("induct_auto_planned"), graded: true },
        { label: "Manual planned", sub: true, value: planned("induct_manual_planned") },
        { label: "Manual actual", sub: true, value: actual("induct_manual_actual"), plan: planned("induct_manual_planned"), graded: true },
        { label: "Target induct PPH", value: () => pva.target_induct_pph },
        {
          label: "Actual induct PPH",
          value: perHour("induct_actual"),
          plan: (c) => (sum(c.rows, "induct_planned") ? pva.target_induct_pph : null),
          graded: true,
          of: "target",
        },
      ],
    },
    {
      title: "Stow",
      rows: [
        { label: "Stow planned", value: planned("stow_planned") },
        { label: "Stow actual", value: actual("stow_actual"), plan: planned("stow_planned"), graded: true },
        { label: "Target stow PPH (per stower)", value: () => pva.target_stow_pph },
        { label: "Actual stow PPH (per stower)", value: stowPph, plan: (c) => (stowPph(c) === null ? null : pva.target_stow_pph), graded: true, of: "target" },
      ],
    },
    {
      title: "Outbound",
      rows: [
        { label: "Pick planned", value: planned("pick_planned") },
        { label: "Pick actual", value: actual("pick_actual"), plan: planned("pick_planned"), graded: true },
      ],
    },
    {
      title: "Station",
      rows: [
        { label: "Station TPH (actual)", value: tph, digits: 1 },
        { label: "Labour hours (actual)", value: laborTotal, digits: 1 },
        ...pva.labor_groups.map((g) => ({
          label: g,
          sub: true,
          value: (c: Col) => (c.future ? null : labor(c.rows, g)),
          digits: 1,
        })),
      ],
    },
  ];
  const fmt = (v: number | null, d = 0): ReactNode =>
    v === null ? <span className="muted">—</span> : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
  const t = pva.plan_totals;
  return (
    <div className="stack">
      <StatRow>
        <Stat label="Planned show hours" value={t.show_hours.toLocaleString()} />
        <Stat label="Needed hours" value={t.needed_hours.toLocaleString()} />
        <Stat label="Planned TPH (with indirect)" value={t.tph_with_indirect ?? "—"} sub={`indirect allowance ${(t.indirect_allowance * 100).toFixed(0)}%`} />
        <Stat label="Planned TPH (without indirect)" value={t.tph_without_indirect ?? "—"} />
        <Stat label="Target induct PPH" value={pva.target_induct_pph.toLocaleString()} />
        <Stat label="Target stow PPH" value={pva.target_stow_pph} sub="per stower" />
      </StatRow>
      <Card title="Plan vs. actual by interval" actions={<IntervalToggle value={n} onChange={setN} />}>
        <div className="v2-grid-wrap">
          <table className="v2-grid" data-testid="pva-grid">
            <thead>
              <tr>
                <th>{n === 0 ? "Cumulative (running totals)" : "All cycles"}</th>
                {cols.map((c) => (
                  <th key={c.label} className="num" data-testid="pva-col">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sections.map((sec) => (
                <Fragment key={sec.title}>
                  <tr className="v2-grid__section">
                    <td>{sec.title}</td>
                    <td colSpan={cols.length} />
                  </tr>
                  {sec.rows.map((r) => (
                    <tr key={r.label} className={r.sub ? "v2-grid__sub" : undefined}>
                      <td>{r.sub ? r.label : <strong>{r.label}</strong>}</td>
                      {cols.map((c) => {
                        const v = r.value(c);
                        const g = r.graded && r.plan ? grade(v, r.plan(c), r.of) : null;
                        return (
                          <td key={c.label} className={`num tabular ${g?.cls ?? ""}`}>
                            {fmt(v, r.digits ?? 0)}
                            {g && <span className={`cell-tag cell-tag--${g.tone}`}>{g.tag}</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12 }}>
          Shading: amber below 90% of plan (or target PPH), red below 70%; every graded cell states its % in text.
          Thresholds are proposed. {pva.note}
        </p>
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
    </div>
  );
}

function clockToMin(clock: string): number {
  const m = /^(\d{1,2}):(\d{2})/.exec(clock ?? "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : 0;
}
