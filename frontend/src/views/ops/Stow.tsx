// Stow & buffers (live): buffer-level metrics (full bays, jackpot rate,
// no-read rate, current volume, share of station volume, avg PPH), the aisle
// fill grid, and the problem-solve queue with rebalancing levers.
import type { LiveState } from "../../api/runtime";
import { pctv } from "../../api/runtime";
import type { Finger, StowCluster } from "../../api/runtimeV2";
import { DataUpdated } from "../../components/DataUpdated";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow } from "../../components/live";

type Buffer = LiveState["views"]["stow_buffers"][number];

export function StowBuffers() {
  return (
    <div>
      <PageHeader eyebrow="Sort" title="Stow & Buffers" badges={<DataSourceBadge kind="simulated" />}>
        Buffer-level stow metrics and aisle bay fill. A full bay overflows to jackpot, cleared by problem solve.
      </PageHeader>
      <LiveGate>{(s) => <StowBody s={s} />}</LiveGate>
    </div>
  );
}

function StowBody({ s }: { s: LiveState }) {
  const snap = s.snapshot;
  const cols: Column<Buffer>[] = [
    { key: "buffer", label: "Buffer" },
    { key: "status", label: "Status", render: (b) => <Pill value={b.status === "active" ? "running" : b.status} label={b.status} /> },
    { key: "full_bays", label: "Full bays", num: true, render: (b) => `${b.full_bays}/${b.bays}` },
    { key: "jackpot_rate", label: "Jackpot rate", num: true, render: (b) => pctv(b.jackpot_rate, 2) },
    { key: "no_read_rate", label: "No-read rate", num: true, render: (b) => pctv(b.no_read_rate, 2) },
    { key: "current_volume", label: "Current volume", num: true },
    { key: "pct_station_volume", label: "% of station volume", num: true, render: (b) => pctv(b.pct_station_volume) },
    { key: "avg_pph", label: "Avg PPH", num: true },
  ];
  return (
    <div className="stack">
      <StatRow>
        <Stat label="Stowers" value={snap.stow.stowers} sub={`plan ${snap.stow.planned_stowers}`} />
        <Stat label="Stow WIP" value={`${snap.stow.wip_minutes.toFixed(1)}m`} sub={`${snap.stow.wip_packages} pkgs · band ${snap.stow.wip_target_min}–${snap.stow.wip_target_max}`} />
        <Stat label="Stowed" value={snap.stow.stowed.toLocaleString()} />
        <Stat label="Jackpot" value={snap.sort.jackpot} />
        <Stat label="Problem solve" value={snap.induct.problem_queue} sub="queued" />
        <Stat label="Flex (VET) left" value={snap.labor.flex_remaining} />
      </StatRow>
      <div className="toolbar-inline">
        <ActButton action={{ kind: "add_stowers", amount: 2 }} label="VET 2 stowers" testId="vet-stowers" />
        <ActButton action={{ kind: "move_associates", target: "stow", amount: 1, params: { from_role: "problem_solve", to_role: "stow" } }} label="Move 1 problem solve → stow" />
        <ActButton action={{ kind: "move_associates", target: "problem_solve", amount: 1, params: { from_role: "stow", to_role: "problem_solve" } }} label="Move 1 stow → problem solve" />
        <ActButton action={{ kind: "open_induct_line" }} label="Open spare induct line" />
      </div>
      <StowBreakdown s={s} />
      <Fingers s={s} />
      <Card title="Stow buffers (aisle groups)">
        <DataTable testId="stow-buffers" columns={cols} rows={s.views.stow_buffers} rowKey={(b) => b.buffer} maxHeight={260} />
        <DataUpdated clock={snap.clock} />
      </Card>
      <Card title="Aisle bay fill">
        <div className="cluster-grid" data-testid="aisle-grid">
          {s.views.layout.aisles.map((a) => {
            const f = a.capacity ? a.level / a.capacity : 0;
            return (
              <div
                key={a.aisle}
                className="cluster-cell"
                title={`${a.aisle}: ${a.level}/${a.capacity}`}
                style={{ background: `color-mix(in srgb, var(--series-1) ${Math.round(f * 70)}%, var(--surface-1))`, color: f > 0.6 ? "#fff" : undefined, borderColor: f >= 1 ? "var(--status-critical)" : undefined }}
              >
                {a.aisle}
                <br />
                {Math.round(f * 100)}%
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

const pct = (v: number | null | undefined, d = 1) => pctv(v, d);

function StowBreakdown({ s }: { s: LiveState }) {
  const rows = s.views.stow_v2.clusters;
  const cols: Column<StowCluster>[] = [
    { key: "cluster", label: "Cluster" },
    { key: "planned", label: "Planned", num: true },
    { key: "arrived", label: "Arrived", num: true },
    { key: "inducted", label: "Inducted", num: true },
    { key: "stow_buffered", label: "Stow buffered", num: true },
    { key: "stowed", label: "Stowed", num: true },
    { key: "stow_plan", label: "Stow / plan", num: true, render: (c) => pct(c.stow_plan) },
    { key: "ps", label: "PS", num: true },
    { key: "jackpot_buffered", label: "Jackpot buffered", num: true },
    { key: "unopened_bags", label: "Unopened bags", num: true },
    { key: "minutes_of_work", label: "Minutes of work", num: true, value: (c) => c.minutes_of_work ?? "—" },
    { key: "stow_rate", label: "Stow rate (/h)", num: true },
    { key: "scan_compliance", label: "Scan comp.", num: true, render: (c) => pct(c.scan_compliance, 2) },
    { key: "active_stowers", label: "Active stowers", num: true },
  ];
  return (
    <Card title="Stow breakdown per cluster">
      <DataTable testId="stow-clusters" columns={cols} rows={rows} rowKey={(c) => c.cluster} maxHeight={320} />
      <DataUpdated clock={s.snapshot.clock} />
    </Card>
  );
}

function Fingers({ s }: { s: LiveState }) {
  const rows = s.views.stow_v2.fingers;
  const cols: Column<Finger>[] = [
    { key: "machine", label: "Machine" },
    {
      key: "status",
      label: "Status",
      render: (f) => (
        <>
          <Pill value={f.status === "Active" ? "running" : "down"} label={f.status} />
          {f.full_bay && <> <Pill value="jam" label="Full bay" /></>}
          {f.rebalanced_to && <span className="muted"> → {f.rebalanced_to}</span>}
        </>
      ),
    },
    { key: "clusters", label: "Clusters", value: (f) => f.clusters.join(", ") },
    {
      key: "buffer",
      label: "Full bay",
      num: true,
      render: (f) => (
        <span title={`${f.full_bay_events} full-bay event(s) today`}>
          {f.buffer}/{f.bay_capacity}
        </span>
      ),
    },
    { key: "jackpot_rate", label: "Jackpot rate", num: true, render: (f) => pct(f.jackpot_rate, 2) },
    { key: "no_read_rate", label: "No-read rate", num: true, render: (f) => pct(f.no_read_rate, 2) },
    { key: "current_volume", label: "Current volume", num: true },
    { key: "pct_station_volume", label: "% station volume", num: true, render: (f) => pct(f.pct_station_volume, 0) },
    { key: "avg_pph", label: "Avg PPH", num: true },
    {
      key: "act",
      label: "",
      render: (f) => <ActButton action={{ kind: "rebalance_finger", target: f.machine }} label="Rebalance" testId={`rebalance-${f.machine}`} />,
    },
  ];
  return (
    <Card title="Stow buffer (fingers)">
      <DataTable
        testId="stow-fingers"
        columns={cols}
        rows={rows}
        rowKey={(f) => f.machine}
        maxHeight={320}
        rowClass={(f) => (f.status === "Down" ? "row-risk" : f.full_bay ? "row-warn" : undefined)}
      />
      <p className="muted" style={{ fontSize: 12 }}>
        A full bay diverts to the jackpot. Rebalance points the finger's clusters at the least-loaded finger (container
        builders follow).
      </p>
      <DataUpdated clock={s.snapshot.clock} />
    </Card>
  );
}

export function ProblemSolve() {
  return (
    <div>
      <PageHeader eyebrow="Sort" title="Problem Solve" badges={<DataSourceBadge kind="simulated" />}>
        No-reads, multi-reads, misapplied labels, damaged packages and jackpot clears waiting for manual resolution.
      </PageHeader>
      <LiveGate>
        {(s) => {
          const ps = s.views.problem_solve;
          return (
            <div className="stack">
              <StatRow>
                <Stat label="Queue" value={ps.queue} />
                <Stat label="Resolved today" value={ps.resolved} />
                {Object.entries(ps.by_reason).map(([k, v]) => (
                  <Stat key={k} label={k.replace(/_/g, " ")} value={v} />
                ))}
                <Stat label="Associates" value={ps.associates.length} sub={ps.associates.join(", ")} />
              </StatRow>
              <div className="toolbar-inline">
                <ActButton action={{ kind: "move_associates", target: "problem_solve", amount: 1, params: { from_role: "stow", to_role: "problem_solve" } }} label="Reinforce: move 1 stow → problem solve" />
              </div>
              <Card title="Queue">
                <DataTable
                  testId="ps-queue"
                  columns={[
                    { key: "tracking_id", label: "Tracking ID", filter: true },
                    { key: "reason", label: "Reason", filter: true, render: (r) => <Pill value={r.reason === "jackpot" ? "planned" : "ready"} label={r.reason?.replace(/_/g, " ")} /> },
                    { key: "route_id", label: "Route", filter: true },
                  ]}
                  rows={ps.items}
                  rowKey={(r) => r.tracking_id}
                  empty="Queue is clear."
                />
              </Card>
            </div>
          );
        }}
      </LiveGate>
    </div>
  );
}
