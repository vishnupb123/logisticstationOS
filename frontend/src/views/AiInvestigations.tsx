import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { LlmStatusBadge } from "../components/LlmStatusBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryStates";

export function AiInvestigations() {
  const queryClient = useQueryClient();
  const executions = useQuery({ queryKey: ["executions"], queryFn: agentsApi.listExecutions });
  const run = useMutation({
    mutationFn: agentsApi.run,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["executions"] });
      // The /run response is the same record GET .../executions/{id}
      // returns (the fallback output is persisted too, since the
      // AgentExecutor root-cause fix) — seeding saves one round trip.
      queryClient.setQueryData(["execution", data.id], data);
    },
  });

  return (
    <div>
      <div className="view-header">
        <h1>Flow Investigations</h1>
        <DataSourceBadge kind="synthetic" />
        <LlmStatusBadge />
      </div>
      <p className="view-subtitle">
        Flow Intelligence Agent runs (Milestone 5) — deterministic observations/calculations from
        the analytics pipeline, plus an LLM-sourced hypothesis/inference/prediction layer. Evidence
        categories are shown as-is, never flattened into plain prose. A run whose LLM step is
        unavailable is <strong>degraded</strong>, not failed: its deterministic findings are complete.
      </p>

      <Card
        title="Executions"
        actions={
          <button className="button button--primary" onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? "Running…" : "Run Flow Intelligence Agent"}
          </button>
        }
      >
        {run.isError && <ErrorState error={run.error} />}
        {executions.isLoading && <LoadingState />}
        {executions.error && <ErrorState error={executions.error} />}
        {executions.data && executions.data.length === 0 && (
          <EmptyState label="No agent executions yet — run the agent above." />
        )}
        {executions.data?.map((e) => (
          <div className="list-item" key={e.id}>
            <div>
              <Link className="list-item__link" to={`/investigations/${e.id}`}>
                {e.agent_name}
              </Link>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {new Date(e.created_at).toLocaleString()}
              </div>
            </div>
            <span className={`status-pill status-pill--${e.status}`}>{e.status}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}
