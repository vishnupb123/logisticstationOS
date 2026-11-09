// Stow & buffers (live): buffer-level metrics (full bays, jackpot rate,
// no-read rate, current volume, share of station volume, avg PPH), the aisle
// fill grid, and the problem-solve queue with rebalancing levers.
import type { LiveState } from "../../api/runtime";
import { pctv } from "../../api/runtime";
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
      <Card title="Stow buffers">
        <DataTable testId="stow-buffers" columns={cols} rows={s.views.stow_buffers} rowKey={(b) => b.buffer} maxHeight={260} />
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
