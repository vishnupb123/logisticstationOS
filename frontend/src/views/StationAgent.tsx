// Station Agent: run a persisted, auditable Station Operations Agent
// investigation (recommendations go to the approval queue), see past
// executions, and see what the agent has learned (its playbook).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { RISK_LABEL, signed, stationOpsApi } from "../api/stationOps";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { LlmStatusBadge } from "../components/LlmStatusBadge";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryStates";
import "./CommandCenter.css";

export function StationAgent() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const presets = useQuery({ queryKey: ["so-presets"], queryFn: stationOpsApi.presets });
  const executions = useQuery({ queryKey: ["so-executions"], queryFn: stationOpsApi.executions });
  const playbook = useQuery({ queryKey: ["so-playbook"], queryFn: stationOpsApi.playbook });
  const [preset, setPreset] = useState("ferry_disruption");
  const [seed, setSeed] = useState(1);
  const [until, setUntil] = useState(1440);
  const run = useMutation({
    mutationFn: () =>
      stationOpsApi.runAgent({ preset, seed, source: "preset", until_minute: until, propose_decisions: true }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["so-executions"] });
      qc.invalidateQueries({ queryKey: ["so-playbook"] });
      qc.invalidateQueries({ queryKey: ["decisions"] });
      qc.setQueryData(["so-execution", data.execution.id], data.execution);
      navigate(`/agent/executions/${data.execution.id}`);
    },
  });

  return (
    <div>
      <PageHeader
        eyebrow="Analyze"
        title="Station Agent"
        badges={
          <>
            <DataSourceBadge kind="simulated" />
            <LlmStatusBadge />
          </>
        }
      >
        The Station Operations Agent investigates a simulated day: detects risks to DEA, OTD, sort
        compliance and timely staging; simulates candidate mitigations; and sends its best plans to the
        approval queue. Deterministic findings never depend on the LLM — the local model only adds
        clearly-labelled hypotheses.
      </PageHeader>

      <Card title="Run an investigation">
        <div className="toolbar">
          <div className="form-row">
            <label htmlFor="sa-preset">Scenario</label>
            <select id="sa-preset" value={preset} onChange={(e) => setPreset(e.target.value)}>
              {(presets.data ?? []).map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
          <div className="form-row">
            <label htmlFor="sa-seed">Seed</label>
            <input
              id="sa-seed"
              type="number"
              value={seed}
              style={{ width: 80 }}
              onChange={(e) => setSeed(Number(e.target.value) || 1)}
            />
          </div>
          <div className="form-row">
            <label htmlFor="sa-until">Investigate up to</label>
            <select id="sa-until" value={until} onChange={(e) => setUntil(Number(e.target.value))}>
              <option value={240}>04:00 (early warning)</option>
              <option value={420}>07:00 (pre pick start)</option>
              <option value={1440}>End of day</option>
            </select>
          </div>
          <button
            className="button button--primary"
            onClick={() => run.mutate()}
            disabled={run.isPending}
            data-testid="sa-run"
          >
            {run.isPending ? "Investigating… (simulating plans + LLM)" : "Run Station Agent"}
          </button>
        </div>
        {run.isError && <ErrorState error={run.error} />}
      </Card>

      <div className="grid-2">
        <Card title="What the agent has learned">
          {playbook.isLoading && <LoadingState />}
          {playbook.error && <ErrorState error={playbook.error} />}
          {playbook.data && playbook.data.stats.length === 0 && (
            <EmptyState label="No experience yet — run the agent here or in the Command Center (advise/autopilot)." />
          )}
          {playbook.data && playbook.data.stats.length > 0 && (
            <>
              <p className="muted cc-foot" style={{ marginTop: 0 }}>
                {playbook.data.episodes} simulated evaluations. {playbook.data.note}
              </p>
              <div className="table-scroll">
                <table data-testid="sa-playbook">
                  <thead>
                    <tr>
                      <th>Risk</th>
                      <th>Situation</th>
                      <th>Plan</th>
                      <th className="num">Episodes</th>
                      <th className="num">Mean ΔDEA</th>
                      <th className="num">Mean score</th>
                      <th className="num">Win rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {playbook.data.stats.map((s) => (
                      <tr key={`${s.risk_type}-${s.situation}-${s.lever_key}`}>
                        <td>{RISK_LABEL[s.risk_type] ?? s.risk_type}</td>
                        <td className="muted" title="time-of-night bucket | levers already in effect">
                          {s.situation}
                        </td>
                        <td>{s.candidate_name}</td>
                        <td className="num tabular">{s.episodes}</td>
                        <td className="num tabular">{signed(s.mean_delta_dea_pp)}</td>
                        <td className="num tabular">{s.mean_score.toFixed(2)}</td>
                        <td className="num tabular">{(s.win_rate * 100).toFixed(0)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
        <Card title="Executions">
          {executions.isLoading && <LoadingState />}
          {executions.error && <ErrorState error={executions.error} />}
          {executions.data?.length === 0 && <EmptyState label="No investigations yet." />}
          {executions.data?.map((e) => (
            <div className="list-item" key={e.id}>
              <div>
                <Link className="list-item__link" to={`/agent/executions/${e.id}`}>
                  Station Operations Agent
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
    </div>
  );
}
