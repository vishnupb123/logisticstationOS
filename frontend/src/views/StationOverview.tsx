import { useQueries } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { analyticsApi } from "../api/analytics";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { Funnel } from "../components/Funnel";
import { Kpi, KpiGrid } from "../components/Kpi";
import { PageHeader } from "../components/PageHeader";
import { ErrorState, LoadingState } from "../components/QueryStates";
import { formatAgo, formatDuration } from "../lib/format";

// The analytics snapshot only changes when the synthetic pipeline is
// re-run (ingest -> Parquet export -> dbt), so polling is cheap and
// honest: it picks that up within one interval, and the header says
// exactly when the numbers were last fetched.
const REFRESH_MS = 15_000;

export function StationOverview() {
  const [jackpot, wips, induct, stow, dwell, e2e] = useQueries({
    queries: [
      { queryKey: ["jackpot-volume"], queryFn: analyticsApi.jackpotVolume, refetchInterval: REFRESH_MS },
      { queryKey: ["wips"], queryFn: analyticsApi.wips, refetchInterval: REFRESH_MS },
      { queryKey: ["induct-throughput"], queryFn: analyticsApi.inductThroughput, refetchInterval: REFRESH_MS },
      { queryKey: ["stow-throughput"], queryFn: analyticsApi.stowThroughput, refetchInterval: REFRESH_MS },
      { queryKey: ["dwell-time"], queryFn: analyticsApi.parcelDwellTime, refetchInterval: REFRESH_MS },
      { queryKey: ["end-to-end"], queryFn: analyticsApi.endToEnd, refetchInterval: REFRESH_MS },
    ],
  });
  const all = [jackpot, wips, induct, stow, dwell, e2e];

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const anyError = all.find((q) => q.error)?.error;
  const anyLoading = all.some((q) => q.isLoading);
  const fetching = all.some((q) => q.isFetching);
  const updatedAt = Math.min(...all.map((q) => q.dataUpdatedAt || 0));
  const refetchAll = () => all.forEach((q) => q.refetch());

  const totalInducted = induct.data?.reduce((sum, b) => sum + b.parcels_inducted, 0) ?? 0;
  const totalStowed = stow.data?.reduce((sum, b) => sum + b.parcels_stowed, 0) ?? 0;
  const stats = e2e.data;
  const jackpotRate =
    stats && stats.parcels_inducted > 0
      ? (stats.parcels_ever_jackpotted / stats.parcels_inducted) * 100
      : 0;
  const completion =
    stats && stats.parcels_inducted > 0
      ? ((stats.parcels_stowed + stats.parcels_exception) / stats.parcels_inducted) * 100
      : 0;

  return (
    <div>
      <PageHeader
        eyebrow="Operate"
        title="Station Overview"
        badges={<DataSourceBadge kind="synthetic" />}
        actions={
          <>
            <span className="refresh-meta" data-testid="refresh-meta">
              {fetching ? "Refreshing…" : `Updated ${formatAgo(updatedAt, now)}`} · auto every{" "}
              {REFRESH_MS / 1000}s
            </span>
            <button className="button" onClick={refetchAll} disabled={fetching}>
              Refresh
            </button>
            <Link to="/live" className="button button--primary" style={{ textDecoration: "none" }}>
              Watch live run →
            </Link>
          </>
        }
      >
        Cycle-1 end-to-end metrics from the analytics pipeline (dbt over the synthetic event log).
        These change when new synthetic events are ingested and the pipeline re-runs. To watch a
        station operate frame by frame, use Live Operations.
      </PageHeader>

      {anyError && <ErrorState error={anyError} />}
      {anyLoading && !anyError && <LoadingState />}

      {!anyLoading && !anyError && stats && (
        <>
          <div className="stack">
            <KpiGrid>
              <Kpi
                testId="kpi-inducted"
                label="Parcels inducted"
                value={totalInducted.toLocaleString()}
                caption="across all hour buckets"
              />
              <Kpi
                label="Parcels stowed"
                value={totalStowed.toLocaleString()}
                caption={`${completion.toFixed(0)}% reached a terminal state`}
              />
              <Kpi
                label="Work in process"
                value={wips.data?.wip_count ?? 0}
                status={(wips.data?.wip_count ?? 0) === 0 ? "good" : "warning"}
                caption="inducted, not yet stowed"
              />
              <Kpi
                label="In jackpot now"
                value={jackpot.data?.currently_in_jackpot ?? 0}
                status={(jackpot.data?.currently_in_jackpot ?? 0) === 0 ? "good" : "warning"}
                caption={`${jackpot.data?.cumulative_diverts ?? 0} diverts · ${jackpot.data?.cumulative_clears ?? 0} clears`}
              />
              <Kpi
                testId="kpi-induct-to-stow"
                label="Induct → stow p50"
                value={formatDuration(stats.induct_to_stow.p50_seconds)}
                caption={`p90 ${formatDuration(stats.induct_to_stow.p90_seconds)} · avg ${formatDuration(dwell.data?.avg_dwell_seconds)}`}
              />
              <Kpi
                label="Jackpot rate"
                value={jackpotRate.toFixed(1)}
                unit="%"
                caption="of inducted parcels ever diverted"
              />
            </KpiGrid>
          </div>

          <div className="grid-2">
            <Card title="End-to-end funnel">
              <Funnel
                stages={[
                  { key: "inducted", label: "Inducted", value: stats.parcels_inducted },
                  {
                    key: "sorted",
                    label: "Sorted to aisle",
                    value: stats.parcels_sorted,
                    note: `${stats.parcels_exception} exception(s) diverted`,
                  },
                  { key: "stowed", label: "Stowed", value: stats.parcels_stowed },
                ]}
              />
              <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
                Percentages are conversion from the previous stage. Exceptions (sideline,
                high-value, future-date) leave Cycle 1 at classification — their downstream
                workflow isn't modeled.
              </p>
            </Card>
            <Card title="Stage cycle times">
              <table>
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>n</th>
                    <th>avg</th>
                    <th>p50</th>
                    <th>p90</th>
                  </tr>
                </thead>
                <tbody>
                  {(
                    [
                      ["Induct → sort", stats.induct_to_sort],
                      ["Sort → stow", stats.sort_to_stow],
                      ["Induct → stow", stats.induct_to_stow],
                    ] as const
                  ).map(([label, d]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      <td className="tabular">{d.count}</td>
                      <td className="tabular">{formatDuration(d.avg_seconds)}</td>
                      <td className="tabular">{formatDuration(d.p50_seconds)}</td>
                      <td className="tabular">{formatDuration(d.p90_seconds)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
                Metric status: <em>proposed</em> — stage boundaries are the event types' own, not a
                validated operational definition.
              </p>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
