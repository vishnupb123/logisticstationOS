import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { decisionsApi } from "../api/decisions";
import type { Role } from "../api/types";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { ErrorState, LoadingState } from "../components/QueryStates";
import { RolePicker } from "../components/RolePicker";

// Matches the scenario the propose form in DecisionHistory.tsx always
// uses — the API doesn't expose which scenario a decision's candidates
// were evaluated against, so the UI tracks it the same way
// scripts/run_decision_demo.py does: as a known constant, not a
// generic lookup.
const SCENARIO = "rl_stow_balancing.yaml";

export function DecisionDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [approverName, setApproverName] = useState("");
  const [approverRole, setApproverRole] = useState<Role>("supervisor");
  const [selectedCandidate, setSelectedCandidate] = useState("");
  const [rationale, setRationale] = useState("");

  const decision = useQuery({
    queryKey: ["decision", id],
    queryFn: () => decisionsApi.get(id!),
    enabled: !!id,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["decision", id] });

  const approve = useMutation({
    mutationFn: () =>
      decisionsApi.approve(id!, {
        approved_by: approverName,
        approver_role: approverRole,
        selected_candidate: selectedCandidate,
        rationale,
      }),
    onSuccess: invalidate,
  });
  const reject = useMutation({
    mutationFn: () =>
      decisionsApi.reject(id!, { approved_by: approverName, approver_role: approverRole, rationale }),
    onSuccess: invalidate,
  });
  const observeOutcome = useMutation({
    mutationFn: () => decisionsApi.observeOutcome(id!, { scenario: SCENARIO }),
    onSuccess: invalidate,
  });

  if (decision.isLoading) return <LoadingState />;
  if (decision.error) return <ErrorState error={decision.error} />;
  if (!decision.data) return null;

  const d = decision.data;
  const actionError = approve.error ?? reject.error ?? observeOutcome.error;

  return (
    <div>
      <Link to="/decisions">&larr; All decisions</Link>
      <div className="view-header" style={{ marginTop: 10 }}>
        <h1>{d.decision_type}</h1>
        <span className={`status-pill status-pill--${d.status}`}>{d.status}</span>
        <DataSourceBadge kind="simulated" />
      </div>
      <p className="view-subtitle">
        Proposed {new Date(d.created_at).toLocaleString()}
        {d.decided_at && ` · decided ${new Date(d.decided_at).toLocaleString()}`}
      </p>

      <Card title="Context & evidence">
        <pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(d.context, null, 2)}</pre>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
          {d.evidence.map((finding, i) => (
            <div key={i}>
              <EvidenceBadge category={finding.category} /> <span>{finding.summary}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Candidates (simulated evaluation)">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Reward</th>
              <th>Max backlog</th>
              <th>Stowed</th>
            </tr>
          </thead>
          <tbody>
            {d.candidates.map((c) => (
              <tr key={c.name} style={{ fontWeight: c.name === d.selected_candidate ? 700 : 400 }}>
                <td>
                  {c.name}
                  {c.name === d.selected_candidate && " ✓"}
                </td>
                <td>{c.evaluation.aggregate.total_reward_mean?.toFixed(2) ?? "—"}</td>
                <td>{c.evaluation.aggregate.max_jackpot_backlog_mean?.toFixed(1) ?? "—"}</td>
                <td>{c.evaluation.aggregate.total_stowed_mean?.toFixed(1) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Policy engine & risk">
        <p>
          Eligible: <strong>{d.policy_engine_result.eligible ? "yes" : "no"}</strong> (policy
          version {d.policy_engine_result.policy_version})
        </p>
        {d.policy_engine_result.violations.length > 0 && (
          <ul>
            {d.policy_engine_result.violations.map((v, i) => (
              <li key={i}>{v}</li>
            ))}
          </ul>
        )}
        <p>
          Blast radius: <strong>{d.risk_evaluation.blast_radius}</strong> (reversible:{" "}
          {d.risk_evaluation.reversible ? "yes" : "no"})
        </p>
        <p style={{ fontSize: 12, color: "var(--text-muted)" }}>{d.risk_evaluation.rationale}</p>
      </Card>

      {d.status === "shadow" && (
        <Card title="Shadow mode">
          <p>
            This decision was proposed in shadow mode — it can never be approved, rejected, or
            have an outcome recorded, by construction (Milestone 9).
          </p>
        </Card>
      )}

      {d.status === "pending_approval" && (
        <Card title="Approve or reject">
          <RolePicker
            name={approverName}
            role={approverRole}
            onNameChange={setApproverName}
            onRoleChange={setApproverRole}
          />
          <div className="form-row" style={{ marginTop: 12 }}>
            <label htmlFor="candidate-select">Selected candidate (for approval)</label>
            <select
              id="candidate-select"
              value={selectedCandidate}
              onChange={(e) => setSelectedCandidate(e.target.value)}
            >
              <option value="">— choose —</option>
              {d.candidates.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label htmlFor="rationale">Rationale</label>
            <textarea
              id="rationale"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              rows={2}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="button button--primary"
              onClick={() => approve.mutate()}
              disabled={approve.isPending || !approverName || !selectedCandidate || !rationale}
            >
              {approve.isPending ? "Approving…" : "Approve"}
            </button>
            <button
              className="button button--danger"
              onClick={() => reject.mutate()}
              disabled={reject.isPending || !approverName || !rationale}
            >
              {reject.isPending ? "Rejecting…" : "Reject"}
            </button>
          </div>
          {actionError && <ErrorState error={actionError} />}
        </Card>
      )}

      {d.status === "approved" && (
        <Card title="Approval">
          <p>
            Approved by <strong>{d.approved_by}</strong> ({d.approver_role}): {d.approval_rationale}
          </p>
          {!d.observed_outcome ? (
            <button
              className="button button--primary"
              onClick={() => observeOutcome.mutate()}
              disabled={observeOutcome.isPending}
            >
              {observeOutcome.isPending ? "Running…" : "Observe outcome"}
            </button>
          ) : (
            <div>
              <p>
                Observed outcome (fresh simulation, recorded{" "}
                {d.outcome_recorded_at && new Date(d.outcome_recorded_at).toLocaleString()}):
              </p>
              <ul>
                <li>Reward: {d.observed_outcome.aggregate.total_reward_mean?.toFixed(2)}</li>
                <li>Max backlog: {d.observed_outcome.aggregate.max_jackpot_backlog_mean?.toFixed(1)}</li>
                <li>Stowed: {d.observed_outcome.aggregate.total_stowed_mean?.toFixed(1)}</li>
              </ul>
            </div>
          )}
          {actionError && <ErrorState error={actionError} />}
        </Card>
      )}

      {d.status === "rejected" && (
        <Card title="Rejection">
          <p>
            Rejected by <strong>{d.approved_by}</strong> ({d.approver_role}): {d.approval_rationale}
          </p>
        </Card>
      )}

      <Card title="Component versions (audit)">
        <pre style={{ fontSize: 12 }}>{JSON.stringify(d.component_versions, null, 2)}</pre>
      </Card>
    </div>
  );
}
