import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { rlApi } from "../api/rl";
import { simulationApi } from "../api/simulation";
import type { PolicyName } from "../api/types";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { ErrorState, LoadingState } from "../components/QueryStates";
import { GroupedBarChart } from "../components/charts/GroupedBarChart";

const POLICY_LABEL: Record<PolicyName, string> = {
  static_baseline: "Static baseline",
  rule_based_baseline: "Rule-based baseline",
};

// Different units/scales per metric — rendered as separate small
// multiples (one chart, one scale, one axis each), never combined
// into one dual-axis chart (the dataviz skill's #1 anti-pattern).
const METRICS: { key: string; label: string; unit: string }[] = [
  { key: "total_reward_mean", label: "Reward", unit: "" },
  { key: "total_stowed_mean", label: "Stowed", unit: "parcels" },
  { key: "max_jackpot_backlog_mean", label: "Max jackpot backlog", unit: "parcels" },
  { key: "constraint_violations_mean", label: "Constraint violations", unit: "" },
];

// Only the "rl_"-prefixed scenario family is actually tuned to create
// real policy-distinguishing contention (docs/RL_ENVIRONMENT_SPEC.md:
// the first scenario attempt never did, confirmed empirically) — the
// twin-exercise scenarios (normal_operations, delayed_inbound_trucks)
// have ample stow capacity relative to volume, so every policy here
// produces near-identical outcomes on them. Default to an "rl_"
// scenario, not just the first one alphabetically, so the view's own
// default isn't silently uninteresting.
function defaultRlScenario(scenarios: { filename: string }[] | undefined): string {
  if (!scenarios || scenarios.length === 0) return "";
  return scenarios.find((s) => s.filename.startsWith("rl_"))?.filename ?? scenarios[0].filename;
}

export function RlComparison() {
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: simulationApi.listScenarios });
  const [scenario, setScenario] = useState("");
  const [seeds, setSeeds] = useState("101,102,103");

  const evaluate = useMutation({
    mutationFn: () =>
      rlApi.evaluate({
        scenario: scenario || defaultRlScenario(scenarios.data),
        seeds: seeds
          .split(",")
          .map((s) => Number(s.trim()))
          .filter((n) => !Number.isNaN(n)),
        policies: ["static_baseline", "rule_based_baseline"],
      }),
  });

  const effectiveScenario = scenario || defaultRlScenario(scenarios.data);
  const policies = evaluate.data ? (Object.keys(evaluate.data.results) as PolicyName[]) : [];

  return (
    <div>
      <div className="view-header">
        <h1>RL Policy Comparison</h1>
        <DataSourceBadge kind="simulated" />
      </div>
      <p className="view-subtitle">
        Compares the static and rule-based baselines (Milestone 6) against a scenario — never the
        trained PPO policy, since the honest finding (docs/RL_ENVIRONMENT_SPEC.md) is that it
        wasn't demonstrably better on the metric that matters. These numbers are a fresh
        simulation run each time, not cached history.
      </p>

      <Card title="Run an evaluation">
        {scenarios.isLoading && <LoadingState />}
        {scenarios.error && <ErrorState error={scenarios.error} />}
        {scenarios.data && (
          <>
            <div className="form-row">
              <label htmlFor="rl-scenario">Scenario</label>
              <select
                id="rl-scenario"
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
            <div className="form-row">
              <label htmlFor="rl-seeds">Seeds (comma-separated, max 20)</label>
              <input id="rl-seeds" value={seeds} onChange={(e) => setSeeds(e.target.value)} />
            </div>
            <button
              className="button button--primary"
              onClick={() => evaluate.mutate()}
              disabled={evaluate.isPending}
            >
              {evaluate.isPending ? "Evaluating…" : "Run evaluation"}
            </button>
          </>
        )}
      </Card>

      {evaluate.isError && <ErrorState error={evaluate.error} />}

      {evaluate.data && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {METRICS.map((metric) => (
            <Card key={metric.key} title={`${metric.label}${metric.unit ? ` (${metric.unit})` : ""}`}>
              <GroupedBarChart
                categories={policies.map((p) => POLICY_LABEL[p])}
                series={[
                  {
                    key: "value",
                    label: metric.label,
                    color: "var(--series-1)",
                    values: policies.map((p) => evaluate.data!.results[p].aggregate[metric.key] ?? 0),
                  },
                ]}
                height={160}
                valueFormatter={(v) => v.toFixed(1)}
              />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
