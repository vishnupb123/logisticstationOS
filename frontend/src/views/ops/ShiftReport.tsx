// Shift report (HANDOFF_V2 E12): a printable one-pager of the simulated day —
// headline KPIs, DEA and OTD with causes, cycle actions, work items, and
// tomorrow's plan — computed by the backend's deterministic analyses and
// watermarked as simulated so it can never be mistaken for a real record.
import { pctv } from "../../api/runtime";
import { type ShiftReport as Report, useReport } from "../../api/runtimeV2";
import { Card } from "../../components/Card";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { ErrorState, LoadingState } from "../../components/QueryStates";
import "./ShiftReport.css";

const KPIS: { key: string; label: string }[] = [
  { key: "dea", label: "DEA" },
  { key: "otd", label: "OTD" },
  { key: "timely_staged", label: "Timely staged" },
  { key: "sort_compliance", label: "Sort compliance" },
  { key: "scan_compliance", label: "Scan compliance" },
  { key: "stow_wip_compliance", label: "Stow WIP compliance" },
  { key: "induct_fph", label: "Induct FPH" },
  { key: "lost_hours", label: "Lost hours" },
  { key: "induct_downtime_dpmo", label: "Downtime DPMO" },
];

function fmtNum(v: number, digits = 2): string {
  return v.toLocaleString(undefined, { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : digits });
}

function fmt(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined) return "—";
  if (unit === "ratio") return pctv(v, 1);
  if (unit === "hours") return `${fmtNum(v)} h`;
  if (unit === "per_hour") return `${fmtNum(v)}/h`;
  return fmtNum(v);
}

function Analysis({ a }: { a: Report["dea"] }) {
  return (
    <div className="rpt-analysis">
      <p className="rpt-headline">{a.headline}</p>
      {a.sections.map((s) => (
        <div key={s.title} className="rpt-section">
          <h3>{s.title}</h3>
          <ul>
            {s.lines.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Body({ r }: { r: Report }) {
  const sess = r.session as { preset?: string; seed?: number; ofd_date?: string; day?: number; minute?: number; scale?: number };
  const wi = r.work_items;
  const t = r.tomorrow;
  const rot = t.rotation ?? {};
  return (
    <div className="rpt" data-testid="shift-report">
      <div className="rpt-watermark" aria-hidden>
        SIMULATED — synthetic data
      </div>
      <div className="rpt-banner" data-testid="report-simulated">
        SIMULATED — synthetic data. A digital-twin run of fictional station NOVA-1; not a record of real operations.
      </div>
      <p className="rpt-meta tabular">
        Day {sess.day ?? 1} · {sess.ofd_date} · scenario {String(sess.preset ?? "").replace(/_/g, " ")} · seed {sess.seed}
        {sess.scale && sess.scale !== 1 ? ` · ${sess.scale}× scale` : ""} · report at sim minute {Math.round(sess.minute ?? 0)}
      </p>

      <section className="rpt-kpis">
        {KPIS.filter((k) => r.metrics[k.key]).map((k) => {
          const m = r.metrics[k.key];
          return (
            <div key={k.key} className="rpt-kpi">
              <div className="rpt-kpi__label">{k.label}</div>
              <div className="rpt-kpi__value tabular">{fmt(m.value, m.unit)}</div>
              <div className="rpt-kpi__target tabular">{m.target === null ? "no target" : `target ${fmt(m.target, m.unit)}`}</div>
            </div>
          );
        })}
      </section>

      <div className="rpt-two">
        <Card title={r.dea.title}>
          <Analysis a={r.dea} />
        </Card>
        <Card title={r.otd.title}>
          <Analysis a={r.otd} />
        </Card>
      </div>

      <div className="rpt-two">
        <Card title="Cycle actions">
          {r.cycles.changes.length === 0 ? (
            <p className="muted">No cycle changes, force inducts or cycle enables were applied.</p>
          ) : (
            <ul className="rpt-list">
              {r.cycles.changes.map((c, i) => (
                <li key={i} className="tabular">
                  {c.clock} · {c.action.replace(/_/g, " ")}
                  {c.minutes ? ` · ${c.minutes} min` : ""}
                  {c.hours ? ` · ${c.hours} h` : ""}
                  {c.packages !== undefined ? ` · ${c.packages.toLocaleString()} packages` : ""}
                </li>
              ))}
            </ul>
          )}
          <p className="muted rpt-small tabular">
            {r.cycles.on_floor_missed_cycle.toLocaleString()} on floor, missed cycle · {r.cycles.next_cycle.toLocaleString()} moved to next cycle ·{" "}
            {r.cycles.held_wrong_cycle.toLocaleString()} held, wrong cycle
          </p>
        </Card>
        <Card title="Work items">
          <dl className="rpt-kv tabular">
            <dt>Completed today</dt>
            <dd>{wi.completed_today}</dd>
            <dt>Expired today</dt>
            <dd>{wi.expired_today}</dd>
            <dt>Dismissed today</dt>
            <dd>{wi.dismissed_today}</dd>
            <dt>Still pending</dt>
            <dd>{wi.pending}</dd>
            <dt>High priority pending</dt>
            <dd>{wi.high_priority}</dd>
            <dt>Carried over</dt>
            <dd>{wi.carried_over}</dd>
          </dl>
        </Card>
      </div>

      <Card title="Tomorrow">
        <div className="rpt-two rpt-two--flat">
          <dl className="rpt-kv tabular">
            <dt>Truckfile version</dt>
            <dd>{t.truckfile_version ? `v${t.truckfile_version}` : "not published yet"}</dd>
            <dt>Labor plan version</dt>
            <dd>{t.plan_version ? `v${t.plan_version}` : "not built yet"}</dd>
            {t.totals && (
              <>
                <dt>Show hours / needed hours</dt>
                <dd>
                  {fmtNum(t.totals.show_hours)} / {fmtNum(t.totals.needed_hours)}
                </dd>
                <dt>Planned TPH (with / without indirect)</dt>
                <dd>
                  {t.totals.tph_with_indirect === null ? "—" : fmtNum(t.totals.tph_with_indirect)} /{" "}
                  {t.totals.tph_without_indirect === null ? "—" : fmtNum(t.totals.tph_without_indirect)}
                </dd>
              </>
            )}
            <dt>Rotation</dt>
            <dd>
              {rot.slots !== undefined
                ? `${rot.filled ?? 0}/${rot.slots} slots filled · ${rot.violations ?? 0} violations${rot.compliance !== undefined ? ` · ${pctv(rot.compliance, 0)} compliant` : ""}`
                : "not run yet"}
            </dd>
          </dl>
          <div>
            <h3 className="rpt-h3">VET / VTO opportunities</h3>
            {t.opportunities.opportunities.length === 0 && t.opportunities.recommendations.length === 0 ? (
              <p className="muted">None posted or recommended.</p>
            ) : (
              <ul className="rpt-list">
                {t.opportunities.opportunities.map((o) => (
                  <li key={o.id} className="tabular">
                    {o.type} {o.time_frame} · {o.headcount} HC · {o.accepted}/{o.submitted} accepted · window {o.window.toLowerCase()}
                  </li>
                ))}
                {t.opportunities.recommendations.map((o, i) => (
                  <li key={`rec-${i}`} className="tabular">
                    Recommended: post {o.headcount} more {o.type} for {o.time_frame}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </Card>
      <p className="muted rpt-small">
        Generated by StationOS from a simulated run. Metric provenance (documented / observed / proposed) is shown in each
        metric's "How this is calculated" drawer.
      </p>
    </div>
  );
}

export function ShiftReport() {
  const q = useReport();
  return (
    <div>
      <PageHeader
        eyebrow="After dispatch"
        title="Shift report"
        badges={<DataSourceBadge kind="simulated" />}
        actions={
          <div className="rpt-actions">
            <button className="button button--sm" onClick={() => q.refetch()} disabled={q.isFetching}>
              {q.isFetching ? "Refreshing…" : "Refresh"}
            </button>
            <button className="button button--primary button--sm" onClick={() => window.print()} data-testid="report-print">
              Print
            </button>
          </div>
        }
      >
        A one-page summary of the simulated day for the shift handover. Refresh to pick up the latest simulated state.
      </PageHeader>
      {q.isLoading ? <LoadingState /> : q.error ? <ErrorState error={q.error} /> : q.data ? <Body r={q.data} /> : null}
    </div>
  );
}
