// Station Command Center — the live station performance summary: headline
// outcome KPIs, induct/lost-hours/downtime/quality cards with their top
// impacted lines, stow metrics, sortation flow, and what the agents are doing.
// Everything reads the one shared live session (simulated, never real ops).
import { Link } from "react-router-dom";
import { type LiveState, pctv } from "../api/runtime";
import { RISK_LABEL } from "../api/stationOps";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { Kpi, KpiGrid, type KpiStatus } from "../components/Kpi";
import { PageHeader } from "../components/PageHeader";
import { TimeSeriesChart } from "../components/charts/TimeSeriesChart";
import { LiveGate } from "../components/live";
import { clockOf } from "../api/stationOps";
import "./CommandCenter.css";

type M = LiveState["snapshot"]["metrics"][string];

function status(m: M | undefined): KpiStatus | undefined {
  if (!m || m.value === null || m.target === null) return undefined;
  if (m.value >= m.target) return "good";
  return m.value >= m.target - 0.01 ? "warning" : "critical";
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
        acting. Metric definitions are <em>proposed</em>; hover a tile for the formula.
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
        <div className="perf-grid">
          <div className="perf-card">
            <div className="perf-card__label">Induct FPH</div>
            <div className="perf-card__split">
              <div>
                <div className="perf-card__value tabular">{snap.induct.fph_last_hour.toLocaleString()}</div>
                <div className="muted perf-card__sub">packages / hour (all lines)</div>
              </div>
              <div>
                <div className="perf-card__value tabular">{snap.induct.inducted.toLocaleString()}</div>
                <div className="muted perf-card__sub">total packages</div>
              </div>
            </div>
            <Top title="Top 3 impacted lines" rows={perf.top_impacted_by_fph.map((l) => ({ label: lineName(l), value: `${l.inducted.toLocaleString()} · ${l.status}` }))} />
          </div>
          <div className="perf-card">
            <div className="perf-card__label">Lost hours</div>
            <div className="perf-card__value tabular">{(m.lost_hours.value ?? 0).toFixed(1)}h</div>
            <div className="muted perf-card__sub">cumulative induct downtime</div>
            <Top title="Top 3 impacted lines" rows={perf.top_impacted_by_lost_hours.filter((l) => l.lost_hours > 0).map((l) => ({ label: lineName(l), value: `${l.lost_hours.toFixed(2)}h` }))} />
          </div>
          <div className="perf-card">
            <div className="perf-card__label">Induct downtime DPMO</div>
            <div className="perf-card__value tabular">{(m.induct_downtime_dpmo.value ?? 0).toLocaleString()}</div>
            <div className="muted perf-card__sub">defects per million opportunities</div>
            <Top title="Top 3 by volume impact" rows={perf.top_impacted_by_dpmo.filter((l) => l.downtime_dpmo > 0).map((l) => ({ label: lineName(l), value: l.downtime_dpmo.toLocaleString() }))} />
          </div>
          <div className="perf-card">
            <div className="perf-card__label">Quality metrics</div>
            <div className="perf-q"><span>No-read</span><strong>{pctv(snap.induct.attempts ? snap.induct.no_reads / snap.induct.attempts : null, 2)}</strong></div>
            <div className="perf-q"><span>Multi-read</span><strong>{pctv(snap.induct.attempts ? snap.induct.multi_reads / snap.induct.attempts : null, 2)}</strong></div>
            <div className="perf-q"><span>Misapplied label</span><strong>{pctv(snap.induct.attempts ? snap.induct.misapplied_labels / snap.induct.attempts : null, 2)}</strong></div>
            <Top title="Top impact by quality issue" rows={perf.top_quality_issues.map((q) => ({ label: q.issue, value: `${q.line} (${pctv(q.rate, 2)})` }))} />
          </div>
        </div>
      </Card>

      <Card title={`Stow metrics (${snap.cycle.name})`}>
        <KpiGrid>
          <Kpi label="Stow PPH / stower" value={m.stow_pph.value === null ? "—" : Math.round(m.stow_pph.value)}
            caption={`target ${m.stow_pph.target}`} />
          <Kpi label="Est. stow WIP compliance" value={pctv(m.stow_wip_compliance.value)} status={status(m.stow_wip_compliance)}
            caption={`target ${pctv(m.stow_wip_compliance.target, 0)}`} />
          <Kpi label="Stow WIP" value={`${snap.stow.wip_minutes.toFixed(1)} min`}
            status={snap.stow.wip_minutes > snap.stow.wip_target_max ? "warning" : snap.stow.wip_minutes >= snap.stow.wip_target_min ? "good" : undefined}
            caption={`target ${snap.stow.wip_target_min}/${snap.stow.wip_target_max} min · ${snap.stow.wip_packages} pkgs`} />
          <Kpi label="Scan compliance" value={pctv(m.scan_compliance.value, 2)} status={status(m.scan_compliance)}
            caption={`${snap.induct.problem_queue} at problem solve`} />
          <Kpi label="Units / labor hour" value={m.units_per_labor_hour.value === null ? "—" : Math.round(m.units_per_labor_hour.value)}
            caption={`${snap.labor.present} on floor · flex ${snap.labor.flex_remaining}`} />
          <Kpi testId="kpi-rollover" label="Rolled over" value={snap.package_status.rolled_over.toLocaleString()}
            status={snap.package_status.rolled_over ? "critical" : "good"} caption="missed the cycle" />
        </KpiGrid>
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
