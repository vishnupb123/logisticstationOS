// The Station Operations Agent's decision log: what it detected, which
// plans it simulated (with metric deltas vs. baseline), what it chose,
// and whether that was applied (autopilot, twin only) or only advised.
import { type AgentAction, RISK_LABEL, signed } from "../api/stationOps";
import { EvidenceBadge } from "./EvidenceBadge";
import "./AgentActionLog.css";

function Delta({ v }: { v: number }) {
  const cls = v > 0.005 ? "delta delta--up" : v < -0.005 ? "delta delta--down" : "delta";
  return <span className={cls}>{signed(v)}</span>;
}

export function AgentActionLog({
  actions,
  emptyLabel = "No risks handled yet.",
}: {
  actions: AgentAction[];
  emptyLabel?: string;
}) {
  if (actions.length === 0) return <p className="muted">{emptyLabel}</p>;
  return (
    <ol className="action-log" data-testid="agent-action-log">
      {[...actions].reverse().map((a, i) => (
        <li key={a.id ?? `${a.minute}-${a.risk.risk_type}-${i}`} className="action-log__item">
          <div className="action-log__head">
            <span className="action-log__clock tabular">{a.clock}</span>
            <span className={`sev sev--${a.risk.severity}`}>{a.risk.severity}</span>
            {a.agent_label && <span className="action-log__agent">{a.agent_label}</span>}
            <strong>{RISK_LABEL[a.risk.risk_type] ?? a.risk.risk_type.replace(/_/g, " ")}</strong>
            {a.kind && a.kind !== "plan" && <span className="outcome-pill">{a.kind === "goal" ? "chat goal" : a.kind}</span>}
            <EvidenceBadge category={a.risk.category} />
            {a.applied ? (
              <span className="outcome-pill outcome-pill--applied">Applied in twin</span>
            ) : a.status === "pending" ? (
              <span className="outcome-pill outcome-pill--advised">Awaiting approval</span>
            ) : a.status === "dismissed" ? (
              <span className="outcome-pill">Dismissed</span>
            ) : a.chosen ? (
              <span className="outcome-pill outcome-pill--advised">Recommended</span>
            ) : a.evaluations.length ? (
              <span className="outcome-pill">Held — no plan worth it</span>
            ) : null}
          </div>
          <p className="action-log__summary">{a.risk.summary}</p>
          {a.evaluations.length > 0 && (
            <div className="table-scroll">
              <table className="action-log__table">
                <thead>
                  <tr>
                    <th>Simulated plan</th>
                    <th className="num">ΔDEA</th>
                    <th className="num">ΔOTD</th>
                    <th className="num">ΔTimely staged</th>
                    <th className="num">Labor h</th>
                    <th className="num">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {a.evaluations.slice(0, 5).map((e) => (
                    <tr key={e.name} className={e.name === a.chosen ? "is-chosen" : undefined}>
                      <td>
                        {e.name === a.chosen && <span aria-label="chosen">✓ </span>}
                        {e.name}
                      </td>
                      <td className="num">
                        <Delta v={e.delta_dea_pp} />
                      </td>
                      <td className="num">
                        <Delta v={e.delta_otd_pp} />
                      </td>
                      <td className="num">
                        <Delta v={e.delta_timely_staged_pp} />
                      </td>
                      <td className="num tabular">{e.labor_hours.toFixed(1)}</td>
                      <td className="num tabular">{e.score.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="action-log__rationale">
            {a.rationale}
            {a.applied_effects.length > 0 && <> Effect: {a.applied_effects.join("; ")}.</>}
          </p>
          {a.deferred && a.deferred.length > 0 && (
            <p className="action-log__note">Deferred by orchestrator: {a.deferred.join("; ")}</p>
          )}
          {a.learned_skips.length > 0 && (
            <p className="action-log__note">Skipped from experience: {a.learned_skips.join("; ")}</p>
          )}
          {a.advisory && <p className="action-log__note">Advisory: {a.advisory}</p>}
        </li>
      ))}
    </ol>
  );
}
