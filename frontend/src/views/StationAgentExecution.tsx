import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { type AgentAction, pct, stationOpsApi } from "../api/stationOps";
import type { Finding } from "../api/types";
import { AgentActionLog } from "../components/AgentActionLog";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { PageHeader } from "../components/PageHeader";
import { ErrorState, LoadingState } from "../components/QueryStates";

interface StationOpsOutput {
  findings: Finding[];
  actions: AgentAction[];
  final_metrics: Record<string, { value: number | null; target: number | null }>;
  interpretation_error: string | null;
  llm_model: string | null;
  decision_ids?: string[];
}

export function StationAgentExecution() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({
    queryKey: ["so-execution", id],
    queryFn: () => stationOpsApi.execution(id!),
    enabled: !!id,
    staleTime: Infinity,
  });
  if (q.isLoading) return <LoadingState />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data) return null;
  const e = q.data;
  const out = e.output as unknown as StationOpsOutput | null;
  const m = out?.final_metrics;

  return (
    <div>
      <Link to="/agent">&larr; Station Agent</Link>
      <PageHeader
        title="Station Operations Agent — investigation"
        badges={
          <>
            <span className={`status-pill status-pill--${e.status}`} data-testid="exec-status">
              {e.status}
            </span>
            <DataSourceBadge kind="simulated" />
          </>
        }
      >
        {String((e.input as Record<string, unknown>).preset)} · seed{" "}
        {String((e.input as Record<string, unknown>).seed)} · started{" "}
        {new Date(e.created_at).toLocaleString()}
        {out?.llm_model && ` · narrative by ${out.llm_model}`}
      </PageHeader>

      {e.status === "degraded" && (
        <Card title="Completed without the LLM narrative">
          <p style={{ margin: 0 }}>
            Every deterministic finding and recommendation below is complete. Only the optional LLM
            hypothesis layer is missing: <span className="muted">{e.error}</span>
          </p>
        </Card>
      )}

      {m && (
        <Card title="Outcome of the simulated day (no mitigations applied — advise mode)">
          <p style={{ margin: 0 }} className="tabular">
            DEA {pct(m.dea?.value ?? m.dea_ceiling?.value)} · OTD {pct(m.otd?.value)} · timely staged{" "}
            {pct(m.timely_staged?.value)} · sort compliance {pct(m.sort_compliance?.value)} · scan
            compliance {pct(m.scan_compliance?.value)}
          </p>
        </Card>
      )}

      {out?.decision_ids && out.decision_ids.length > 0 && (
        <Card title="Sent to the approval queue">
          <ul data-testid="exec-decisions">
            {out.decision_ids.map((d) => (
              <li key={d}>
                <Link to={`/decisions/${d}`}>Decision {d.slice(0, 8)}</Link> — pending approval
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Findings">
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }} data-testid="exec-findings">
          {(out?.findings ?? []).map((f, i) => (
            <div key={i} style={{ borderBottom: "1px solid var(--gridline)", paddingBottom: 8 }}>
              <EvidenceBadge category={f.category} />
              <p style={{ margin: "6px 0" }}>{f.summary}</p>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Decision log">
        <AgentActionLog actions={out?.actions ?? []} />
      </Card>
    </div>
  );
}
