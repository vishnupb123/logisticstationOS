// Truckfile & Ferries: the day's planned linehauls, with the daily ferry
// check that turns a sailing's status into a revised ETA. The ferry
// provider here is synthetic (seeded) — a real operator feed would be a
// drop-in adapter behind the same interface (backend/app/inbound/ferry.py).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { runtimeApi } from "../api/runtime";
import { type RefreshSummary, type TruckfileTrip, stationOpsApi } from "../api/stationOps";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { Kpi, KpiGrid } from "../components/Kpi";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryStates";
import "./CommandCenter.css";

function tomorrow(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

function hhmm(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hour12: false,
  });
}

const FERRY_LABEL: Record<TruckfileTrip["ferry_status"], string> = {
  not_applicable: "road",
  unknown: "not checked",
  on_time: "on time",
  delayed: "delayed",
  cancelled: "cancelled",
};

export function Truckfile() {
  const qc = useQueryClient();
  const [date, setDate] = useState(tomorrow);
  const [weather, setWeather] = useState<string>("");
  const [summary, setSummary] = useState<RefreshSummary | null>(null);
  const file = useQuery({
    queryKey: ["truckfile", date],
    queryFn: () => stationOpsApi.truckfile(date),
    enabled: !!date,
  });
  const refresh = useMutation({
    mutationFn: () =>
      stationOpsApi.refreshTruckfile({ ofd_date: date, weather: weather || null, seed: 1 }),
    onSuccess: (data) => {
      setSummary(data.summary);
      qc.setQueryData(["truckfile", date], { ofd_date: date, exists: true, trips: data.trips });
    },
  });
  const navigate = useNavigate();
  const simulate = useMutation({
    mutationFn: () =>
      runtimeApi.create({ preset: "normal_day", source: "truckfile", ofd_date: date, mode: "autopilot", speed: 2 }),
    onSuccess: () => {
      qc.invalidateQueries();
      navigate("/command");
    },
  });
  const trips = file.data?.trips ?? [];
  const ferry = trips.filter((t) => t.via_ferry);
  const atRisk = ferry.filter((t) => t.ferry_status === "delayed" || t.ferry_status === "cancelled");

  return (
    <div>
      <PageHeader
        eyebrow="Operate"
        title="Truckfile & Ferries"
        badges={<DataSourceBadge kind="synthetic" />}
      >
        Planned linehauls for an out-for-delivery date. The daily refresh checks every ferry-borne
        trip's sailing and writes the revised ETA back to the truckfile — the Command Center and the
        Station Agent then plan the day against those ETAs. Ferry statuses come from a seeded
        synthetic provider, not a real operator.
      </PageHeader>

      <Card>
        <div className="toolbar">
          <div className="form-row">
            <label htmlFor="tf-date">OFD date</label>
            <input id="tf-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="form-row">
            <label htmlFor="tf-weather">Crossing weather</label>
            <select id="tf-weather" value={weather} onChange={(e) => setWeather(e.target.value)}>
              <option value="">Drawn from seed</option>
              <option value="calm">Calm</option>
              <option value="rough">Rough</option>
              <option value="severe">Severe</option>
            </select>
          </div>
          <button
            className="button button--primary"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending || !date}
          >
            {refresh.isPending
              ? "Checking ferries…"
              : file.data?.exists
                ? "Refresh ferry status"
                : "Create truckfile & check ferries"}
          </button>
          {file.data?.exists && (
            <button
              className="button"
              data-testid="tf-simulate"
              disabled={simulate.isPending}
              onClick={() => simulate.mutate()}
            >
              {simulate.isPending ? "Starting…" : "Run this day live →"}
            </button>
          )}
        </div>
        {refresh.isError && <ErrorState error={refresh.error} />}
        {summary && (
          <p className="muted cc-desc" data-testid="tf-summary">
            Checked {summary.ferry_trips} ferry trips via {summary.provider} at{" "}
            {new Date(summary.checked_at).toLocaleTimeString()} — {summary.delayed} delayed,{" "}
            {summary.cancelled} cancelled, {summary.changes.length} changed since the last check.
          </p>
        )}
      </Card>

      {file.isLoading && <LoadingState />}
      {file.error && <ErrorState error={file.error} />}
      {file.data && !file.data.exists && (
        <Card>
          <EmptyState label="No truckfile for this date yet — create it to generate the day's synthetic linehaul plan and run the first ferry check." />
        </Card>
      )}

      {trips.length > 0 && (
        <>
          <div className="stack">
            <KpiGrid>
              <Kpi label="Linehauls" value={trips.length} caption={`${ferry.length} via ferry`} />
              <Kpi
                label="Planned volume"
                value={trips.reduce((a, t) => a + t.volume, 0).toLocaleString()}
                caption="packages"
              />
              <Kpi
                testId="tf-at-risk"
                label="Ferry trips delayed/cancelled"
                value={atRisk.length}
                status={atRisk.length ? "critical" : "good"}
                caption={`${atRisk.reduce((a, t) => a + t.volume, 0).toLocaleString()} pkgs affected`}
              />
              <Kpi
                label="Max ferry delay"
                value={Math.max(0, ...ferry.map((t) => t.delay_minutes))}
                unit="min"
              />
            </KpiGrid>
          </div>
          <Card title={`Truckfile — ${date}`}>
            <div className="table-scroll">
              <table data-testid="tf-table">
                <thead>
                  <tr>
                    <th>Trip</th>
                    <th>Origin</th>
                    <th>Sailing</th>
                    <th>Planned</th>
                    <th>Revised ETA</th>
                    <th>Ferry status</th>
                    <th className="num">Delay</th>
                    <th>Reason</th>
                    <th className="num">Volume</th>
                    <th className="num">Checks</th>
                  </tr>
                </thead>
                <tbody>
                  {trips.map((t) => (
                    <tr
                      key={t.trip_id}
                      className={t.ferry_status === "delayed" || t.ferry_status === "cancelled" ? "row-risk" : undefined}
                    >
                      <td className="tabular">{t.trip_id}</td>
                      <td>{t.origin}</td>
                      <td>{t.ferry_sailing ?? "—"}</td>
                      <td className="tabular">{hhmm(t.planned_arrival)}</td>
                      <td className="tabular">{t.via_ferry ? hhmm(t.revised_arrival) : hhmm(t.planned_arrival)}</td>
                      <td>
                        <span className={`trip-status trip-status--${t.ferry_status === "on_time" ? "arrived" : t.ferry_status}`}>
                          {FERRY_LABEL[t.ferry_status]}
                        </span>
                      </td>
                      <td className="num tabular">{t.delay_minutes ? `${t.delay_minutes} min` : "—"}</td>
                      <td className="muted">{t.delay_reason ?? "—"}</td>
                      <td className="num tabular">{t.volume.toLocaleString()}</td>
                      <td className="num tabular">{t.checks}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted cc-foot">
              Times are station-local (UTC in this synthetic setup). Automate the daily refresh with{" "}
              <code>python scripts/refresh_truckfile.py --date YYYY-MM-DD</code> on a schedule.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
