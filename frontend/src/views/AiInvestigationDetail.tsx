import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { EvidenceBadge } from "../components/EvidenceBadge";
import { ErrorState, LoadingState } from "../components/QueryStates";

export function AiInvestigationDetail() {
  const { id } = useParams<{ id: string }>();
  const execution = useQuery({
    queryKey: ["execution", id],
    queryFn: () => agentsApi.getExecution(id!),
    enabled: !!id,
    // A completed/failed execution's data never changes after the
    // fact — and AiInvestigations.tsx seeds this exact query key with
    // the real in-memory result right after a run, which a default
    // (stale-on-mount) refetch would immediately clobber with the
    // honestly-less-complete persisted row (see that file's comment).
    staleTime: Infinity,
  });

  if (execution.isLoading) return <LoadingState />;
  if (execution.error) return <ErrorState error={execution.error} />;
  if (!execution.data) return null;

  const { data } = execution;

  return (
    <div>
      <Link to="/investigations">&larr; All executions</Link>
      <div className="view-header" style={{ marginTop: 10 }}>
        <h1>{data.agent_name}</h1>
        <span className={`status-pill status-pill--${data.status}`}>{data.status}</span>
        <DataSourceBadge kind="synthetic" />
      </div>
      <p className="view-subtitle">
        Started {new Date(data.created_at).toLocaleString()}
        {data.completed_at && ` · completed ${new Date(data.completed_at).toLocaleString()}`}
      </p>

      {data.output?.interpretation_error && (
        <Card title="Interpretation error">
          <ErrorState error={new Error(data.output.interpretation_error)} />
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
            The LLM interpretation step failed after retries (e.g. no Ollama server reachable) —
            the deterministic findings below are still real, never fabricated to compensate.
          </p>
        </Card>
      )}

      <Card title="Findings">
        {!data.output || data.output.findings.length === 0 ? (
          <p style={{ color: "var(--text-muted)" }}>No findings.</p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {data.output.findings.map((finding, i) => (
              <div key={i} style={{ borderBottom: "1px solid var(--gridline)", paddingBottom: 10 }}>
                <EvidenceBadge category={finding.category} />
                <p style={{ margin: "6px 0" }}>{finding.summary}</p>
                {finding.supporting_evidence.length > 0 && (
                  <p style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    Evidence: {finding.supporting_evidence.join(", ")}
                  </p>
                )}
                {finding.confidence != null && (
                  <p style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    Confidence: {(finding.confidence * 100).toFixed(0)}%
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {data.error && (
        <Card title="Execution error">
          <ErrorState error={new Error(data.error)} />
        </Card>
      )}
    </div>
  );
}
