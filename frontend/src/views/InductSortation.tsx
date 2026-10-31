import { useQuery } from "@tanstack/react-query";
import { analyticsApi } from "../api/analytics";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryStates";
import { LineChart } from "../components/charts/LineChart";

export function InductSortation() {
  const induct = useQuery({ queryKey: ["induct-throughput"], queryFn: analyticsApi.inductThroughput });

  return (
    <div>
      <div className="view-header">
        <h1>Induct &amp; Sortation</h1>
        <DataSourceBadge kind="synthetic" />
      </div>
      <p className="view-subtitle">
        Parcels inducted per hour bucket (<code>metric_induct_throughput</code>,
        docs/OPERATIONAL_DOMAIN_MODEL.md §4.1) — a `proposed`-status metric, not yet validated
        against a domain owner's exact definition.
      </p>

      <Card title="Induct throughput by hour">
        {induct.isLoading && <LoadingState />}
        {induct.error && <ErrorState error={induct.error} />}
        {induct.data && induct.data.length === 0 && (
          <EmptyState label="No induct events in the current analytics export." />
        )}
        {induct.data && induct.data.length > 0 && (
          <LineChart
            points={induct.data.map((b) => ({
              label: new Date(b.hour_bucket).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "numeric",
              }),
              value: b.parcels_inducted,
            }))}
            valueFormatter={(v) => `${v} parcel(s)`}
          />
        )}
      </Card>
    </div>
  );
}
