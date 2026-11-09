// Agent console (live): the five specialist agents and what each is
// watching, recommendations awaiting human approval (copilot mode), and the
// full decision log — reflexes, robust counterfactual plans, arbitration,
// learned skips — for the live simulated day.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { type LiveState, runtimeApi, useControl } from "../../api/runtime";
import { RISK_LABEL } from "../../api/stationOps";
import { AgentActionLog } from "../../components/AgentActionLog";
import { Card } from "../../components/Card";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { LlmStatusBadge } from "../../components/LlmStatusBadge";
import { PageHeader } from "../../components/PageHeader";
import { LiveGate, Pill } from "../../components/live";

const AGENTS = [
  { key: "inbound", label: "Inbound Agent", does: "Linehaul & ferry ETAs, yard and unload sequence" },
  { key: "sort_stow", label: "Sort & Stow Agent", does: "Induct & stow capacity, WIP band, problem solve, VET" },
  { key: "outbound", label: "Outbound Agent", does: "Route prioritisation, pick labor, stage-by" },
  { key: "dispatch", label: "Dispatch Agent", does: "DSP drivers: reminders, rerouting, standby, swipe" },
  { key: "quality", label: "Quality & HV Agent", does: "High-value cage, sort & scan compliance" },
];

export function AgentConsole() {
  return (
    <div>
      <PageHeader
        eyebrow="AI"
        title="Agent Console"
        badges={
          <>
            <DataSourceBadge kind="simulated" />
            <LlmStatusBadge />
          </>
        }
        actions={<Link className="button" to="/agent/investigations">Investigations & learned playbook →</Link>}
      >
        Five specialist agents coordinated by an orchestrator. Each cycle they sense (known information only), take
        low-risk reflex actions, simulate candidate plans across several uncertain futures, arbitrate shared labor, and
        act — on the simulated station only — or ask you to approve.
      </PageHeader>
      <LiveGate>{(s) => <Body s={s} />}</LiveGate>
    </div>
  );
}

function Body({ s }: { s: LiveState }) {
  const qc = useQueryClient();
  const control = useControl();
  const decide = useMutation({
    mutationFn: ({ id, verb }: { id: number; verb: "approve" | "dismiss" }) => runtimeApi.decide(id, verb),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live-state"] }),
  });
  const mode = s.agents.mode;
  return (
    <div className="stack">
      <div className="toolbar-inline">
        <span className="muted">Mode:</span>
        <div className="seg" role="group" aria-label="Agent mode">
          {(["autopilot", "advise", "observe"] as const).map((m) => (
            <button key={m} aria-pressed={mode === m} onClick={() => control.mutate({ mode: m })} data-testid={`mode-${m}`}>
              {m === "advise" ? "copilot (approve each)" : m}
            </button>
          ))}
        </div>
        {s.agents.busy && <Pill value="running" label="simulating plans…" />}
      </div>
      <div className="agent-grid">
        {AGENTS.map((a) => {
          const risks = s.agents.risks.filter((r) => r.agent === a.key);
          const acts = s.agents.actions.filter((x) => x.agent === a.key);
          const last = acts[acts.length - 1];
          return (
            <div key={a.key} className="agent-card" data-testid={`agent-${a.key}`}>
              <div className="agent-card__head">
                <strong>{a.label}</strong>
                <Pill value={risks.some((r) => r.severity === "critical") ? "down" : risks.length ? "ready" : "running"} label={risks.length ? `${risks.length} risk(s)` : "clear"} />
              </div>
              <div className="muted agent-card__does">{a.does}</div>
              {risks.slice(0, 2).map((r, i) => (
                <div key={i} className="agent-card__risk">
                  {RISK_LABEL[r.risk_type] ?? r.risk_type.replace(/_/g, " ")}
                </div>
              ))}
              <div className="agent-card__foot muted">
                {acts.filter((x) => x.applied).length} applied · {acts.length} decisions
                {last ? ` · last ${last.clock}` : ""}
              </div>
            </div>
          );
        })}
      </div>
      {s.agents.pending.length > 0 && (
        <Card title={`Awaiting your approval (${s.agents.pending.length})`}>
          <ul className="work-items" data-testid="pending-recs">
            {s.agents.pending.map((p) => (
              <li key={p.id}>
                <span className="tabular">{p.clock}</span>
                <span className="muted">{p.agent_label}</span>
                <span className="work-items__title">
                  <strong>{p.chosen}</strong> — {p.rationale}
                </span>
                <button className="button button--primary button--sm" onClick={() => decide.mutate({ id: p.id, verb: "approve" })} data-testid={`approve-${p.id}`}>
                  Approve
                </button>
                <button className="button button--sm" onClick={() => decide.mutate({ id: p.id, verb: "dismiss" })}>
                  Dismiss
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title={`Decision log (${s.agents.actions.length} most recent)`}>
        <AgentActionLog actions={s.agents.actions} emptyLabel="No decisions yet — the agents run every 15 simulated minutes." />
      </Card>
    </div>
  );
}
