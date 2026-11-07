// Live Operations: the digital twin played back step by step over
// Server-Sent Events (GET /simulation/live), so the whole Cycle-1 flow
// — truck arrival -> induct -> sort (or jackpot) -> stow — can be
// watched progressing, with end-to-end metrics updating every frame.
//
// This is the answer to "if it's mimicking a station, I should see the
// progress": the *operational* views read the synthetic event log's
// analytics snapshot (which only changes when the pipeline reruns),
// while this view watches a simulated run unfold. It is always badged
// "Simulated run" — never presented as live operational truth
// (ADR-0002/ADR-0006).
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useLiveTwin } from "../api/live";
import { simulationApi } from "../api/simulation";
import type { LiveSnapshot, StageDuration } from "../api/types";
import { Card } from "../components/Card";
import { DataSourceBadge } from "../components/DataSourceBadge";
import { Funnel } from "../components/Funnel";
import { HamperGrid } from "../components/HamperGrid";
import { Kpi, KpiGrid } from "../components/Kpi";
import { Meter } from "../components/Meter";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/QueryStates";
import { TimeSeriesChart } from "../components/charts/TimeSeriesChart";
import { formatDuration } from "../lib/format";
import "./LiveOperations.css";

const PACE_OPTIONS = [
  { label: "Real-time-ish (slow)", stepSeconds: 15, frameIntervalMs: 400 },
  { label: "Standard", stepSeconds: 30, frameIntervalMs: 200 },
  { label: "Fast", stepSeconds: 60, frameIntervalMs: 80 },
  { label: "Instant (no pacing)", stepSeconds: 60, frameIntervalMs: 0 },
];

const THROUGHPUT_WINDOW_SECONDS = 600;

function simMinutes(seconds: number): string {
  const m = Math.floor(seconds / 60);
  return `T+${m}m`;
}

function throughputPerHour(history: LiveSnapshot[]): number {
  if (history.length < 2) return 0;
  const latest = history[history.length - 1];
  const windowStart = latest.sim_time_seconds - THROUGHPUT_WINDOW_SECONDS;
  const base = history.find((s) => s.sim_time_seconds >= windowStart) ?? history[0];
  const elapsed = latest.sim_time_seconds - base.sim_time_seconds;
  if (elapsed <= 0) return 0;
  return ((latest.funnel.parcels_stowed - base.funnel.parcels_stowed) / elapsed) * 3600;
}

function StageRow({ label, stats }: { label: string; stats: StageDuration }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="tabular">{stats.count}</td>
      <td className="tabular">{formatDuration(stats.avg_seconds)}</td>
      <td className="tabular">{formatDuration(stats.p50_seconds)}</td>
      <td className="tabular">{formatDuration(stats.p90_seconds)}</td>
    </tr>
  );
}

function defaultScenario(filenames: string[]): string {
  return filenames.find((f) => f === "normal_operations.yaml") ?? filenames[0] ?? "";
}

export function LiveOperations() {
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: simulationApi.listScenarios });
  const [scenario, setScenario] = useState("");
  const [seed, setSeed] = useState("");
  const [paceIndex, setPaceIndex] = useState(1);
  const live = useLiveTwin();

  const effectiveScenario =
    scenario || defaultScenario(scenarios.data?.map((s) => s.filename) ?? []);
  const running = live.status === "streaming" || live.status === "connecting";
  const s = live.latest;

  const tickerEvents = useMemo(
    () =>
      live.history
        .slice(-8)
        .flatMap((snap) => snap.recent_events)
        .slice(-40)
        .reverse(),
    [live.history],
  );

  const x = live.history.map((h) => h.sim_time_seconds);
  const terminal = s ? s.funnel.parcels_stowed + s.funnel.parcels_exception : 0;
  const progressPct = s && s.planned_parcels > 0 ? (terminal / s.planned_parcels) * 100 : 0;
  const totalWip = s
    ? s.wip.awaiting_induct + s.wip.inducting + s.wip.in_jackpot + s.wip.awaiting_stow + s.wip.stowing
    : 0;
  const fullHampers = s ? s.hampers.filter((h) => h.level >= h.capacity).length : 0;

  const start = () => {
    const pace = PACE_OPTIONS[paceIndex];
    live.start({
      scenario: effectiveScenario,
      seed: seed.trim() === "" ? undefined : Number(seed),
      stepSeconds: pace.stepSeconds,
      frameIntervalMs: pace.frameIntervalMs,
    });
  };

  return (
    <div>
      <PageHeader
        eyebrow="Operate"
        title="Live Operations"
        badges={<DataSourceBadge kind="simulated" />}
      >
        Watch a digital-twin run of Station NOVA-1 progress through truck arrival → induct → sort →
        stow in simulated time, with end-to-end metrics recomputed every frame. A hypothetical run
        played back live — not a feed of real operations.
      </PageHeader>

      <Card>
        {scenarios.isLoading && <LoadingState />}
        {scenarios.error && <ErrorState error={scenarios.error} />}
        {scenarios.data && (
          <div className="toolbar">
            <div className="form-row">
              <label htmlFor="live-scenario">Scenario</label>
              <select
                id="live-scenario"
                value={effectiveScenario}
                disabled={running}
                onChange={(e) => setScenario(e.target.value)}
              >
                {scenarios.data.map((sc) => (
                  <option key={sc.filename} value={sc.filename}>
                    {sc.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <label htmlFor="live-seed">Seed</label>
              <input
                id="live-seed"
                type="number"
                value={seed}
                disabled={running}
                placeholder="scenario default"
                onChange={(e) => setSeed(e.target.value)}
                style={{ width: 140 }}
              />
            </div>
            <div className="form-row">
              <label htmlFor="live-pace">Playback</label>
              <select
                id="live-pace"
                value={paceIndex}
                disabled={running}
                onChange={(e) => setPaceIndex(Number(e.target.value))}
              >
                {PACE_OPTIONS.map((p, i) => (
                  <option key={p.label} value={i}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
            {running ? (
              <button className="button button--danger" onClick={live.stop}>
                Stop
              </button>
            ) : (
              <button
                className="button button--primary"
                onClick={start}
                disabled={!effectiveScenario}
              >
                {live.status === "idle" ? "Start live run" : "Restart run"}
              </button>
            )}
            <div className="live-status" data-testid="live-status">
              <span className={`live-dot live-dot--${live.status}`} aria-hidden />
              {
                {
                  idle: "Not started",
                  connecting: "Connecting…",
                  streaming: "Streaming",
                  complete: "Run complete",
                  stopped: "Stopped",
                  error: "Stream error",
                }[live.status]
              }
            </div>
          </div>
        )}
        {s && (
          <div className="live-progress">
            <div className="live-progress__meta">
              <span>
                Sim clock{" "}
                <strong className="tabular" data-testid="sim-clock">
                  {new Date(s.sim_clock).toLocaleTimeString(undefined, { timeZone: "UTC" })} UTC
                </strong>
              </span>
              <span className="muted tabular">
                {simMinutes(s.sim_time_seconds)} · frame {s.frame}
              </span>
              <span className="tabular">
                {terminal}/{s.planned_parcels} parcels processed ({progressPct.toFixed(0)}%)
              </span>
            </div>
            <div className="progress">
              <div className="progress__fill" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        )}
      </Card>

      {live.error && <ErrorState error={new Error(live.error)} />}

      {!s && !live.error && (
        <Card>
          <EmptyState label="Start a live run to watch the station operate. Metrics populate as simulated time advances." />
        </Card>
      )}

      {s && (
        <>
          <div className="stack">
            <KpiGrid>
              <Kpi
                testId="kpi-stowed"
                label="Parcels stowed"
                value={s.funnel.parcels_stowed.toLocaleString()}
                caption={`of ${s.funnel.parcels_inducted} inducted`}
              />
              <Kpi
                label="Throughput"
                value={Math.round(throughputPerHour(live.history)).toLocaleString()}
                unit="/hr"
                caption="stowed, trailing 10 sim-min"
              />
              <Kpi
                label="Work in process"
                value={totalWip}
                caption="all stages, right now"
              />
              <Kpi
                label="In jackpot now"
                value={s.wip.in_jackpot}
                status={s.wip.in_jackpot === 0 ? "good" : s.wip.in_jackpot < 10 ? "warning" : "critical"}
                caption={`${s.funnel.jackpot_diverts} diverts total`}
              />
              <Kpi
                testId="kpi-dock-to-stow"
                label="Dock-to-stow p50"
                value={formatDuration(s.cycle_times.dock_to_stow.p50_seconds)}
                caption={`p90 ${formatDuration(s.cycle_times.dock_to_stow.p90_seconds)}`}
              />
              <Kpi
                label="Hampers full"
                value={`${fullHampers}/${s.hampers.length}`}
                status={fullHampers === 0 ? "good" : "warning"}
                caption="full hampers force jackpot"
              />
            </KpiGrid>
          </div>

          <div className="grid-2">
            <Card title="End-to-end flow">
              <Funnel
                total={s.planned_parcels}
                stages={[
                  {
                    key: "planned",
                    label: "Planned",
                    value: s.planned_parcels,
                    note: `${s.funnel.trucks_arrived} truck(s) arrived`,
                  },
                  { key: "inducted", label: "Inducted", value: s.funnel.parcels_inducted },
                  {
                    key: "sorted",
                    label: "Sorted to aisle",
                    value: s.funnel.parcels_sorted,
                    note: `${s.funnel.parcels_exception} exception(s) diverted`,
                  },
                  { key: "stowed", label: "Stowed", value: s.funnel.parcels_stowed },
                ]}
              />
              <table className="live-stage-table">
                <thead>
                  <tr>
                    <th>Stage cycle time</th>
                    <th>n</th>
                    <th>avg</th>
                    <th>p50</th>
                    <th>p90</th>
                  </tr>
                </thead>
                <tbody>
                  <StageRow label="Induct → sort" stats={s.cycle_times.induct_to_sort} />
                  <StageRow label="Sort → stow" stats={s.cycle_times.sort_to_stow} />
                  <StageRow label="Induct → stow" stats={s.cycle_times.induct_to_stow} />
                  <StageRow label="Dock → stow (end to end)" stats={s.cycle_times.dock_to_stow} />
                </tbody>
              </table>
            </Card>
            <Card title="Resources & work in process">
              <Meter
                label="Induct stations busy"
                value={s.utilization.induct_busy}
                max={s.utilization.induct_capacity}
              />
              <Meter
                label="Stowers busy"
                value={s.utilization.stowers_busy}
                max={s.utilization.stower_capacity}
              />
              <table>
                <tbody>
                  <tr>
                    <td>Waiting for induct</td>
                    <td className="tabular">{s.wip.awaiting_induct}</td>
                  </tr>
                  <tr>
                    <td>Inducting</td>
                    <td className="tabular">{s.wip.inducting}</td>
                  </tr>
                  <tr>
                    <td>In jackpot</td>
                    <td className="tabular">{s.wip.in_jackpot}</td>
                  </tr>
                  <tr>
                    <td>Sorted, waiting for stower</td>
                    <td className="tabular">{s.wip.awaiting_stow}</td>
                  </tr>
                  <tr>
                    <td>Being stowed</td>
                    <td className="tabular">{s.wip.stowing}</td>
                  </tr>
                </tbody>
              </table>
            </Card>
          </div>

          <div className="grid-2" style={{ marginTop: 16 }}>
            <Card title="Work in process by stage">
              <TimeSeriesChart
                ariaLabel="Work in process by stage over simulated time"
                x={x}
                xFormatter={simMinutes}
                series={[
                  {
                    key: "induct",
                    label: "Induct queue",
                    color: "var(--series-1)",
                    values: live.history.map((h) => h.wip.awaiting_induct + h.wip.inducting),
                  },
                  {
                    key: "jackpot",
                    label: "In jackpot",
                    color: "var(--series-2)",
                    values: live.history.map((h) => h.wip.in_jackpot),
                  },
                  {
                    key: "stow",
                    label: "Awaiting / in stow",
                    color: "var(--series-3)",
                    values: live.history.map((h) => h.wip.awaiting_stow + h.wip.stowing),
                  },
                ]}
              />
            </Card>
            <Card title="Cumulative parcels">
              <TimeSeriesChart
                ariaLabel="Cumulative parcels inducted and stowed over simulated time"
                x={x}
                xFormatter={simMinutes}
                series={[
                  {
                    key: "inducted",
                    label: "Inducted",
                    color: "var(--series-1)",
                    values: live.history.map((h) => h.funnel.parcels_inducted),
                  },
                  {
                    key: "stowed",
                    label: "Stowed",
                    color: "var(--series-3)",
                    values: live.history.map((h) => h.funnel.parcels_stowed),
                  },
                ]}
              />
            </Card>
          </div>

          <div className="grid-2" style={{ marginTop: 16 }}>
            <Card title={`Hamper fill by aisle (${s.hampers.length})`}>
              <HamperGrid hampers={s.hampers} />
            </Card>
            <Card title="Event stream">
              <div className="ticker" data-testid="event-ticker">
                {tickerEvents.length === 0 && <EmptyState label="No events yet." />}
                {tickerEvents.map((e, i) => (
                  <div className="ticker__row" key={`${e.occurred_at}-${e.correlation_id}-${i}`}>
                    <span className="ticker__time tabular">
                      {new Date(e.occurred_at).toLocaleTimeString(undefined, { timeZone: "UTC" })}
                    </span>
                    <code className="ticker__type">{e.event_type}</code>
                    <span className="ticker__id">{e.correlation_id}</span>
                    <span className="ticker__detail">{e.detail ?? ""}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
