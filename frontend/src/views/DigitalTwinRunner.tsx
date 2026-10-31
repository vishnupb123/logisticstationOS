import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { simulationApi } from "../api/simulation";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { ErrorState, LoadingState } from "../components/QueryStates";

export function DigitalTwinRunner() {
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: simulationApi.listScenarios });
  const [scenario, setScenario] = useState<string>("");
  const [seed, setSeed] = useState<string>("");

  const run = useMutation({
    mutationFn: () =>
      simulationApi.run({
        scenario,
        seed: seed.trim() === "" ? undefined : Number(seed),
      }),
  });

  const selected = scenarios.data?.find((s) => s.filename === scenario) ?? scenarios.data?.[0];
  const effectiveScenario = scenario || scenarios.data?.[0]?.filename || "";

  return (
    <div>
      <div className="view-header">
        <h1>Digital Twin Scenario Runner</h1>
        <DataSourceBadge kind="simulated" />
      </div>
      <p className="view-subtitle">
        Runs a shipped SimPy scenario (Milestone 4) synchronously and returns a summary — never
        the raw event list, never a disk write. Every result here is a hypothetical run, not a
        record of anything that happened.
      </p>

      <Card title="Run a scenario">
        {scenarios.isLoading && <LoadingState />}
        {scenarios.error && <ErrorState error={scenarios.error} />}
        {scenarios.data && (
          <>
            <div className="form-row">
              <label htmlFor="scenario-select">Scenario</label>
              <select
                id="scenario-select"
                value={effectiveScenario}
                onChange={(e) => setScenario(e.target.value)}
              >
                {scenarios.data.map((s) => (
                  <option key={s.filename} value={s.filename}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            {selected && (
              <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: -6, marginBottom: 12 }}>
                {selected.description}
              </p>
            )}
            <div className="form-row">
              <label htmlFor="seed-input">Seed override (optional)</label>
              <input
                id="seed-input"
                type="number"
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
                placeholder="use the scenario file's own seed"
              />
            </div>
            <button
              className="button button--primary"
              onClick={() => run.mutate()}
              disabled={run.isPending || !effectiveScenario}
            >
              {run.isPending ? "Running…" : "Run scenario"}
            </button>
          </>
        )}
      </Card>

      {run.isError && <ErrorState error={run.error} />}

      {run.data && (
        <Card title={`Result: ${run.data.scenario_name} (seed ${run.data.seed})`}>
          <DataSourceBadge kind="simulated" />
          <p style={{ marginTop: 10 }}>
            <strong>{run.data.event_count}</strong> event(s) generated at{" "}
            {new Date(run.data.generated_at).toLocaleString()} (run id <code>{run.data.run_id}</code>)
          </p>
          <table>
            <thead>
              <tr>
                <th>Event type</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(run.data.event_type_counts)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => (
                  <tr key={type}>
                    <td>
                      <code>{type}</code>
                    </td>
                    <td>{count}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
