// Station Command Center — the live station performance summary: headline
// outcome KPIs, induct/lost-hours/downtime/quality cards with their top
// impacted lines, stow metrics, sortation flow, and what the agents are doing.
// Everything reads the one shared live session (simulated, never real ops).
import { Link } from "react-router-dom";
import { type LiveState, type Snapshot, pctv } from "../api/runtime";
import { RISK_LABEL } from "../api/stationOps";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { Kpi, KpiGrid, type KpiStatus } from "../components/Kpi";
import { PageHeader } from "../components/PageHeader";
import { TimeSeriesChart } from "../components/charts/TimeSeriesChart";
import { LiveGate } from "../components/live";
import { DataUpdated, MetricInfo } from "../components/MetricDrawer";
import { clockOf } from "../api/stationOps";
import "./CommandCenter.css";

type M = LiveState["snapshot"]["metrics"][string];

function status(m: M | undefined): KpiStatus | undefined {
  if (!m || m.value === null || m.target === null) return undefined;
  if (m.value >= m.target) return "good";
  return m.value >= m.target - 0.01 ? "warning" : "critical";
}

interface QualityRow {
  line: string;
  attempts: number;
  no_read: number;
  multi_read: number;
  misapplied_label: number;
}

function fmtInt(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : Math.round(v).toLocaleString();
}

/** `[[line, value], …]` from the metric engine's inputs. */
function pairs(v: unknown): [string, number][] {
  if (!Array.isArray(v)) return [];
  return v.filter((x) => Array.isArray(x) && x.length === 2).map((x) => [String(x[0]), Number(x[1]) || 0] as [string, number]).slice(0, 3);
}

/** Attempts-weighted rate across lines. */
function avgRate(rows: QualityRow[], k: "no_read" | "multi_read" | "misapplied_label"): number | null {
  const att = rows.reduce((a, r) => a + r.attempts, 0);
  return att ? rows.reduce((a, r) => a + r[k] * r.attempts, 0) / att : null;
}

function fphStatus(m: M | undefined): KpiStatus | undefined {
  if (!m || m.value === null || !m.target) return undefined;
  if (m.value >= m.target) return "good";
  return m.value >= m.target * 0.9 ? "warning" : "critical";
}

function wipStatus(m: M): KpiStatus | undefined {
  if (m.value === null || m.target === null) return undefined;
  if (m.inputs?.no_flow) return "critical";
  const hi = m.target_max ?? Infinity;
  if (m.value > hi) return "critical";
  return m.value >= m.target ? "good" : "warning";
}

const STATUS_TEXT: Record<KpiStatus, string> = { good: "On track", warning: "Watch", critical: "Action" };

function StatusText({ status }: { status: KpiStatus | undefined }) {
  if (!status) return null;
  return (
    <span className={`kpi__status kpi__status--${status} perf-status`}>
      <span className="kpi__dot" aria-hidden />
      {STATUS_TEXT[status]} vs. dynamic target
    </span>
  );
}

function Top({ title, rows }: { title: string; rows: { label: string; value: string }[] }) {
  return (
    <div className="perf-top">
      <div className="perf-top__title">⚠ {title}</div>
      {rows.length === 0 ? (
        <div className="muted">—</div>
      ) : (
        rows.map((r) => (
          <div key={r.label} className="perf-top__row">
            <span>{r.label}</span>
            <strong className="tabular">{r.value}</strong>
          </div>
        ))
      )}
    </div>
  );
}

export function CommandCenter() {
  return (
    <div>
      <PageHeader eyebrow="Operate" title="Station Command Center" badges={<DataSourceBadge kind="simulated" />}>
        Live performance of station NOVA-1's simulated operating day — linehauls (incl. ferry-borne) → receive →
        induct → sort → stow → pick → stage → DSP dispatch → delivery — with five specialist agents watching and
        acting. Every tile's ⓘ opens "How this is calculated": formula, provenance (documented / observed / proposed) and current inputs.
      </PageHeader>
      <LiveGate>{(s) => <Body s={s} />}</LiveGate>
    </div>
  );
}

function Body({ s }: { s: LiveState }) {
  const snap = s.snapshot;
  const m = snap.metrics;
  const perf = s.views.performance;
  const lineName = (l: { line: string }) => l.line;
  const ind = snap.induct as Snapshot["induct"] & { quality_by_line?: QualityRow[]; top_quality_issue?: { issue: string; line: string; rate: number } | null };
  const quality = ind.quality_by_line ?? [];
  const topQ = ind.top_quality_issue ?? null;
  const wip = m.stow_wip_minutes ?? { key: "stow_wip_minutes", value: snap.stow.wip_minutes, target: snap.stow.wip_target_min, target_max: snap.stow.wip_target_max, unit: "minutes" as const };
  return (
    <div className="stack">
      <KpiGrid>
        <Kpi
          testId="kpi-dea"
          label="Delivery Estimate Accuracy"
          value={snap.done ? pctv(m.dea.value, 2) : pctv(m.dea_ceiling.value, 2)}
          status={status(snap.done ? m.dea : m.dea_ceiling)}
          caption={snap.done ? `final · target ${pctv(m.dea.target)}` : `best case so far · ${snap.delivery.known_misses} known misses`}
        />
        <Kpi testId="kpi-otd" label="On-Time Departure" value={pctv(m.otd.value)} status={status(m.otd)}
          caption={`vs original plan ${pctv(m.otd_original_plan.value)}`} />
        <Kpi label="Sort Compliance" value={pctv(m.sort_compliance.value, 2)} status={status(m.sort_compliance)}
          caption={`${snap.sort.missorts} missorts`} />
        <Kpi label="Timely Staged" value={pctv(m.timely_staged.value)} status={status(m.timely_staged)}
          caption={`${snap.outbound.at_risk ?? 0} routes at risk`} />
        <Kpi label="HV custody" value={pctv(m.hv_custody_compliance.value)} status={status(m.hv_custody_compliance)}
          caption="two custody scans" />
        <Kpi label="Swipe-to-finish" value={pctv(m.swipe_compliance.value)} status={status(m.swipe_compliance)}
          caption={`RTS rate ${pctv(m.rts_rate.value)}`} />
      </KpiGrid>

      <Card title="Station performance summary">
        <div className="perf-grid" data-testid="perf-summary">
          <div className="perf-card" data-testid="perf-induct-fph">
            <div className="perf-card__label">
              Induct FPH <MetricInfo metricKey="induct_fph" />
            </div>
            <div className="perf-card__split">
              <div>
                <div className="perf-card__value tabular">{fmtInt(m.induct_fph?.value)}</div>
                <div className="muted perf-card__sub">actual (rolling 10 min × 6)</div>
              </div>
              <div>
                <div className="perf-card__value perf-card__value--target tabular">{fmtInt(m.induct_fph?.target)}</div>
                <div className="muted perf-card__sub">dynamic target</div>
              </div>
            </div>
            <StatusText status={fphStatus(m.induct_fph)} />
            <Top title="Top 3 impacted lines" rows={perf.top_impacted_by_fph.slice(0, 3).map((l) => ({ label: lineName(l), value: `${l.inducted.toLocaleString()} · ${l.status}` }))} />
          </div>
          <div className="perf-card" data-testid="perf-lost-hours">
            <div className="perf-card__label">
              Lost hours <MetricInfo metricKey="lost_hours" />
            </div>
            <div className="perf-card__value tabular">{(m.lost_hours?.value ?? 0).toFixed(2)}h</div>
            <div className="muted perf-card__sub">belt gaps of 20–120 s, all lines</div>
            <Top title="Top 3 impacted lines" rows={pairs(m.lost_hours?.inputs?.top_3).filter(([, v]) => v > 0).map(([l, v]) => ({ label: l, value: `${v.toFixed(2)}h` }))} />
          </div>
          <div className="perf-card" data-testid="perf-dpmo">
            <div className="perf-card__label">
              Induct downtime DPMO <MetricInfo metricKey="induct_downtime_dpmo" />
            </div>
            <div className="perf-card__value tabular">{fmtInt(m.induct_downtime_dpmo?.value)}</div>
            <div className="muted perf-card__sub">stops per million inducted</div>
            <Top title="Top 3 by volume impact" rows={pairs(m.induct_downtime_dpmo?.inputs?.top_3_by_volume_impact).filter(([, v]) => v > 0).map(([l, v]) => ({ label: l, value: `${v.toLocaleString()} stops` }))} />
          </div>
          <div className="perf-card" data-testid="perf-quality">
            <div className="perf-card__label">
              Quality <MetricInfo metricKey="quality" labelOverride="Induct quality" />
            </div>
            {quality.length > 0 ? (
              <>
                <div className="perf-q"><span>No-read</span><strong className="tabular">{pctv(avgRate(quality, "no_read"), 2)}</strong></div>
                <div className="perf-q"><span>Multi-read</span><strong className="tabular">{pctv(avgRate(quality, "multi_read"), 2)}</strong></div>
                <div className="perf-q"><span>Misapplied label</span><strong className="tabular">{pctv(avgRate(quality, "misapplied_label"), 2)}</strong></div>
              </>
            ) : (
              <>
                <div className="perf-q"><span>No-read</span><strong>{pctv(snap.induct.attempts ? snap.induct.no_reads / snap.induct.attempts : null, 2)}</strong></div>
                <div className="perf-q"><span>Multi-read</span><strong>{pctv(snap.induct.attempts ? snap.induct.multi_reads / snap.induct.attempts : null, 2)}</strong></div>
                <div className="perf-q"><span>Misapplied label</span><strong>{pctv(snap.induct.attempts ? snap.induct.misapplied_labels / snap.induct.attempts : null, 2)}</strong></div>
              </>
            )}
            <Top
              title="Top impact by quality issue"
              rows={
                topQ
                  ? [{ label: topQ.issue.replace(/_/g, " "), value: `${topQ.line} (${pctv(topQ.rate, 2)})` }]
                  : perf.top_quality_issues.slice(0, 1).map((q) => ({ label: q.issue, value: `${q.line} (${pctv(q.rate, 2)})` }))
              }
            />
          </div>
        </div>
        <DataUpdated />
      </Card>

      <Card title={`Stow metrics (${snap.cycle.name})`}>
        <KpiGrid>
          <Kpi testId="kpi-stow-fph" label="Stow FPH" value={fmtInt(m.stow_fph?.value)} status={fphStatus(m.stow_fph)}
            caption={<>target {fmtInt(m.stow_fph?.target)} (dynamic) <MetricInfo metricKey="stow_fph" /></>} />
          <Kpi testId="kpi-stow-wip-compliance" label="Est. stow WIP compliance" value={pctv(m.stow_wip_compliance?.value)} status={status(m.stow_wip_compliance)}
            caption={<>target {pctv(m.stow_wip_compliance?.target, 0)} <MetricInfo metricKey="stow_wip_compliance" /></>} />
          <Kpi testId="kpi-stow-wip" label="Stow WIP" value={wip.value === null || wip.value === undefined ? "—" : `${wip.value.toFixed(1)} min`}
            status={wipStatus(wip)}
            caption={<>band {fmtInt(wip.target)}–{fmtInt(wip.target_max)} min · {snap.stow.wip_packages.toLocaleString()} pkgs <MetricInfo metricKey="stow_wip_minutes" /></>} />
          <Kpi label="Stow PPH / stower" value={m.stow_pph?.value == null ? "—" : Math.round(m.stow_pph.value)}
            caption={<>target {m.stow_pph?.target ?? "—"} <MetricInfo metricKey="stow_pph" /></>} />
          <Kpi label="Scan compliance" value={pctv(m.scan_compliance.value, 2)} status={status(m.scan_compliance)}
            caption={`${snap.induct.problem_queue} at problem solve`} />
          <Kpi label="Units / labor hour" value={m.units_per_labor_hour.value === null ? "—" : Math.round(m.units_per_labor_hour.value)}
            caption={`${snap.labor.present} on floor · flex ${snap.labor.flex_remaining}`} />
          <Kpi testId="kpi-rollover" label="Rolled over" value={snap.package_status.rolled_over.toLocaleString()}
            status={snap.package_status.rolled_over ? "critical" : "good"} caption="missed the cycle" />
        </KpiGrid>
        <DataUpdated />
      </Card>

      <div className="grid-2">
        <Card title="Sortation flow (packages per 15 min)">
          <TimeSeriesChart
            ariaLabel="Packages arrived, inducted, stowed and picked per 15 minutes"
            x={snap.series.minute ?? []}
            xFormatter={clockOf}
            series={[
              { key: "arrived", label: "Arrived", color: "var(--series-1)", values: snap.series.arrived ?? [] },
              { key: "inducted", label: "Inducted", color: "var(--series-2)", values: snap.series.inducted ?? [] },
              { key: "stowed", label: "Stowed", color: "var(--series-3)", values: snap.series.stowed ?? [] },
              { key: "picked", label: "Picked", color: "var(--series-7)", values: snap.series.picked ?? [] },
            ]}
          />
        </Card>
        <Card title="Agents right now" actions={<Link to="/agent" className="button button--sm">Agent console →</Link>}>
          <p className="muted" style={{ marginTop: 0 }}>
            Mode <strong>{s.agents.mode === "advise" ? "copilot" : s.agents.mode}</strong>
            {s.agents.busy ? " · simulating plans…" : ""} · {s.agents.pending.length} awaiting approval
          </p>
          {s.agents.risks.length === 0 ? (
            <p className="muted">No open risks.</p>
          ) : (
            <ul className="cc-risk-list" data-testid="cc-risks">
              {s.agents.risks.slice(0, 6).map((r, i) => (
                <li key={`${r.risk_type}-${i}`}>
                  <span className={`sev sev--${r.severity}`}>{r.severity}</span>{" "}
                  <strong>{RISK_LABEL[r.risk_type] ?? r.risk_type.replace(/_/g, " ")}</strong>
                  <div className="muted">{r.summary}</div>
                </li>
              ))}
            </ul>
          )}
          <h3 className="cc-subhead">Latest actions</h3>
          <ul className="cc-iv-list" data-testid="cc-interventions">
            {snap.interventions_applied.slice(-8).reverse().map((iv, i) => (
              <li key={i}>
                <span className="tabular">{iv.clock}</span> {iv.effect}{" "}
                <span className="muted">({iv.source.replace(/_/g, " ")})</span>
              </li>
            ))}
            {snap.interventions_applied.length === 0 && <li className="muted">None yet.</li>}
          </ul>
        </Card>
      </div>
    </div>
  );
}
