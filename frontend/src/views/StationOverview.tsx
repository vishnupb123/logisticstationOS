import { useQuery } from "@tanstack/react-query";
import { analyticsApi } from "../api/analytics";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { ErrorState, LoadingState } from "../components/QueryStates";
import { StatTile } from "../components/StatTile";

export function StationOverview() {
  const jackpot = useQuery({ queryKey: ["jackpot-volume"], queryFn: analyticsApi.jackpotVolume });
  const wips = useQuery({ queryKey: ["wips"], queryFn: analyticsApi.wips });
  const induct = useQuery({ queryKey: ["induct-throughput"], queryFn: analyticsApi.inductThroughput });
  const stow = useQuery({ queryKey: ["stow-throughput"], queryFn: analyticsApi.stowThroughput });
  const dwell = useQuery({ queryKey: ["dwell-time"], queryFn: analyticsApi.parcelDwellTime });

  const anyError = jackpot.error ?? wips.error ?? induct.error ?? stow.error ?? dwell.error;
  const anyLoading =
    jackpot.isLoading || wips.isLoading || induct.isLoading || stow.isLoading || dwell.isLoading;

  const totalInducted = induct.data?.reduce((sum, b) => sum + b.parcels_inducted, 0) ?? 0;
  const totalStowed = stow.data?.reduce((sum, b) => sum + b.parcels_stowed, 0) ?? 0;

  return (
    <div>
      <div className="view-header">
        <h1>Station Overview</h1>
        <DataSourceBadge kind="synthetic" />
      </div>
      <p className="view-subtitle">
        Cycle-1 metrics from the Milestone 3 analytics pipeline (dbt over the synthetic event
        log). This is a snapshot of whatever data currently exists in the analytics DuckDB file —
        not a live feed.
      </p>

      {anyError && <ErrorState error={anyError} />}
      {anyLoading && !anyError && <LoadingState />}

      {!anyLoading && !anyError && (
        <Card title="Key metrics">
          <div className="stat-grid">
            <StatTile
              label="Currently in jackpot"
              value={jackpot.data?.currently_in_jackpot ?? 0}
              caption={`${jackpot.data?.cumulative_diverts ?? 0} diverts, ${jackpot.data?.cumulative_clears ?? 0} clears (cumulative)`}
            />
            <StatTile label="Work in process" value={wips.data?.wip_count ?? 0} caption="inducted, not yet stowed" />
            <StatTile label="Total inducted" value={totalInducted} caption="across all hour buckets" />
            <StatTile label="Total stowed" value={totalStowed} caption="across all hour buckets" />
            <StatTile
              label="Avg dwell time"
              value={dwell.data?.avg_dwell_seconds != null ? `${Math.round(dwell.data.avg_dwell_seconds)}s` : "—"}
              caption={`over ${dwell.data?.parcel_count ?? 0} stowed parcel(s)`}
            />
          </div>
        </Card>
      )}
    </div>
  );
}
