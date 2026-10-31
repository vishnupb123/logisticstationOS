import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { decisionsApi } from "../api/decisions";
import type { CandidateIntervention } from "../api/types";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryStates";

// The same three named candidates scripts/run_decision_demo.py uses —
// this form targets the rl_stow_balancing scenario family specifically
// (6 aisles, A1-A6). A generic per-scenario aisle-weight builder would
// need the API to expose a scenario's aisle layout, which it doesn't
// yet (docs/OPEN_QUESTIONS.md) — not built this session.
const PRESET_CANDIDATES: CandidateIntervention[] = [
  {
    name: "status_quo",
    description: "Uniform stow priority across all aisles — no reallocation.",
    priority_weights: { A1: 0.5, A2: 0.5, A3: 0.5, A4: 0.5, A5: 0.5, A6: 0.5 },
  },
  {
    name: "favor_first_half",
    description: "Favor aisles A1-A3 (weight 0.9) over A4-A6 (weight 0.1).",
    priority_weights: { A1: 0.9, A2: 0.9, A3: 0.9, A4: 0.1, A5: 0.1, A6: 0.1 },
  },
  {
    name: "favor_second_half",
    description: "Favor aisles A4-A6 (weight 0.9) over A1-A3 (weight 0.1).",
    priority_weights: { A1: 0.1, A2: 0.1, A3: 0.1, A4: 0.9, A5: 0.9, A6: 0.9 },
  },
];

const STATUS_FILTERS = ["", "pending_approval", "approved", "rejected", "shadow"];

export function DecisionHistory() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [trigger, setTrigger] = useState("Manual proposal from the command centre");
  const [shadow, setShadow] = useState(false);

  const decisions = useQuery({
    queryKey: ["decisions", statusFilter],
    queryFn: () => decisionsApi.list(statusFilter || undefined),
  });

  const propose = useMutation({
    mutationFn: () =>
      decisionsApi.propose({
        decision_type: "aisle_stow_priority",
        context: { trigger },
        evidence: [
          {
            category: "observation",
            summary: trigger,
            supporting_evidence: [],
            confidence: null,
            alternative_explanations: [],
          },
        ],
        scenario: "rl_stow_balancing.yaml",
        candidates: PRESET_CANDIDATES,
        shadow,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["decisions"] }),
  });

  return (
    <div>
      <div className="view-header">
        <h1>Decisions &amp; Audit History</h1>
        <DataSourceBadge kind="simulated" />
      </div>
      <p className="view-subtitle">
        The decision-governance pipeline (Milestones 7 &amp; 9) — RBAC-checked approval, a
        permanent audit record, and a shadow mode that can never be approved. Candidate
        evaluation is always a fresh simulation run, never real operational history.
      </p>

      <Card title="Propose a decision">
        <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: -4 }}>
          Targets the <code>rl_stow_balancing.yaml</code> scenario with three preset candidates
          (the same ones <code>scripts/run_decision_demo.py</code> uses) — not a generic
          candidate builder.
        </p>
        <div className="form-row">
          <label htmlFor="trigger">Context / trigger</label>
          <input id="trigger" value={trigger} onChange={(e) => setTrigger(e.target.value)} />
        </div>
        <div className="form-row" style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <input
            id="shadow"
            type="checkbox"
            checked={shadow}
            onChange={(e) => setShadow(e.target.checked)}
          />
          <label htmlFor="shadow" style={{ margin: 0 }}>
            Shadow mode (never eligible for approval)
          </label>
        </div>
        <button className="button button--primary" onClick={() => propose.mutate()} disabled={propose.isPending}>
          {propose.isPending ? "Proposing…" : "Propose decision"}
        </button>
        {propose.isError && <ErrorState error={propose.error} />}
      </Card>

      <Card
        title="History"
        actions={
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>
                {s || "all statuses"}
              </option>
            ))}
          </select>
        }
      >
        {decisions.isLoading && <LoadingState />}
        {decisions.error && <ErrorState error={decisions.error} />}
        {decisions.data && decisions.data.length === 0 && (
          <EmptyState label="No decisions yet — propose one above." />
        )}
        {decisions.data?.map((d) => (
          <div className="list-item" key={d.id}>
            <div>
              <Link className="list-item__link" to={`/decisions/${d.id}`}>
                {d.decision_type}
              </Link>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {new Date(d.created_at).toLocaleString()} · {d.candidates.length} candidate(s)
              </div>
            </div>
            <span className={`status-pill status-pill--${d.status}`}>{d.status}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}
