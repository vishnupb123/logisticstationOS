import { useQuery } from "@tanstack/react-query";
import { analyticsApi } from "../api/analytics";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryStates";
import { StatTile } from "../components/StatTile";
import { GroupedBarChart, type BarSeries } from "../components/charts/GroupedBarChart";

// Fixed categorical slot order (dataviz skill) — never generated per
// however many stowers happen to appear in one export.
const SERIES_COLORS = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
  "var(--series-7)",
  "var(--series-8)",
];

export function StowJackpot() {
  const jackpot = useQuery({ queryKey: ["jackpot-volume"], queryFn: analyticsApi.jackpotVolume });
  const stow = useQuery({ queryKey: ["stow-throughput"], queryFn: analyticsApi.stowThroughput });

  const categories = Array.from(new Set((stow.data ?? []).map((b) => b.hour_bucket))).sort();
  const stowerCodes = Array.from(
    new Set((stow.data ?? []).map((b) => b.stower_code ?? "unknown")),
  ).slice(0, 8); // the categorical palette's all-pairs-safe cap is 3; beyond 8 slots entirely, fold to "Other" — not needed at this station's scale.

  const series: BarSeries[] = stowerCodes.map((code, i) => ({
    key: code,
    label: code,
    color: SERIES_COLORS[i % SERIES_COLORS.length],
    values: categories.map(
      (hour) =>
        stow.data?.find((b) => b.hour_bucket === hour && (b.stower_code ?? "unknown") === code)
          ?.parcels_stowed ?? 0,
    ),
  }));

  const categoryLabels = categories.map((c) =>
    new Date(c).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" }),
  );

  return (
    <div>
      <div className="view-header">
        <h1>Stow &amp; Jackpot</h1>
        <DataSourceBadge kind="synthetic" />
      </div>
      <p className="view-subtitle">
        Stow throughput by hour and stower (<code>metric_stow_throughput</code>), and the current
        jackpot backlog (<code>metric_jackpot_volume</code>) — both `proposed`-status metrics.
      </p>

      <Card title="Jackpot volume">
        {jackpot.isLoading && <LoadingState />}
        {jackpot.error && <ErrorState error={jackpot.error} />}
        {jackpot.data && (
          <div className="stat-grid">
            <StatTile label="Currently in jackpot" value={jackpot.data.currently_in_jackpot} />
            <StatTile label="Cumulative diverts" value={jackpot.data.cumulative_diverts} />
            <StatTile label="Cumulative clears" value={jackpot.data.cumulative_clears} />
          </div>
        )}
      </Card>

      <Card title="Stow throughput by hour and stower">
        {stow.isLoading && <LoadingState />}
        {stow.error && <ErrorState error={stow.error} />}
        {stow.data && stow.data.length === 0 && (
          <EmptyState label="No stow events in the current analytics export." />
        )}
        {stow.data && stow.data.length > 0 && (
          <GroupedBarChart
            categories={categoryLabels}
            series={series}
            valueFormatter={(v) => `${v} parcel(s)`}
          />
        )}
      </Card>
    </div>
  );
}
