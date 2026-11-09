// High-value processing (live): the secure cage flow — induct → custody
// scan-in → cage → handoff to the route's staged cart (second custody scan)
// → dispatch — with cage dwell, queue, associates and per-package custody.
import { pctv } from "../../api/runtime";
import { Card } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow } from "../../components/live";

const FLOW = [
  ["hv_pending_scan_in", "Pending scan-in"],
  ["hv_in_cage", "In cage"],
  ["picked", "Handed off"],
  ["staged", "On staged cart"],
  ["on_road", "Dispatched"],
] as const;

export function HighValue() {
  return (
    <div>
      <PageHeader eyebrow="Outbound" title="High-Value Processing" badges={<DataSourceBadge kind="simulated" />}>
        High-value packages bypass regular stow: a custody scan-in to the secure cage, then a custody handoff onto the
        route's staged cart. A route can't finish staging until its HV packages are handed off.
      </PageHeader>
      <LiveGate>
        {(s) => {
          const hv = s.views.high_value;
          const counts = Object.fromEntries(FLOW.map(([k]) => [k, hv.packages.filter((p) => p.status === k).length]));
          return (
            <div className="stack">
              <StatRow>
                <Stat label="HV packages today" value={hv.total} />
                <Stat label="Pending scan-in" value={hv.pending_scan_in} />
                <Stat label="In cage" value={hv.in_cage} sub={hv.avg_cage_dwell_minutes ? `avg dwell ${hv.avg_cage_dwell_minutes} min` : undefined} />
                <Stat label="Handed off" value={hv.handed_off} />
                <Stat label="Dispatched" value={hv.dispatched} />
                <Stat label="Custody compliance" value={pctv(hv.custody_compliance)} />
                <Stat label="Cage queue" value={hv.queue} sub={`${hv.associates.length} HV associate(s)`} />
              </StatRow>
              <div className="toolbar-inline">
                <ActButton action={{ kind: "move_associates", target: "high_value", amount: 1, params: { from_role: "problem_solve", to_role: "high_value" } }} label="Reinforce cage (problem solve → HV)" testId="hv-reinforce" />
                <ActButton action={{ kind: "move_associates", target: "high_value", amount: 1, params: { from_role: "pick", to_role: "high_value" } }} label="Reinforce cage (pick → HV)" />
                <span className="muted" style={{ fontSize: 12 }}>
                  HV associates: {hv.associates.join(", ") || "none present"}
                </span>
              </div>
              <Card title="Custody flow">
                <div className="hv-flow" data-testid="hv-flow">
                  {FLOW.map(([k, label], i) => (
                    <div key={k} className="hv-flow__step">
                      <div className="hv-flow__n tabular">{counts[k]}</div>
                      <div className="muted">{label}</div>
                      {i < FLOW.length - 1 && <span className="hv-flow__arrow">→</span>}
                    </div>
                  ))}
                </div>
              </Card>
              <Card title="High-value packages">
                <DataTable
                  testId="hv-table"
                  columns={[
                    { key: "tracking_id", label: "Tracking ID", filter: true },
                    { key: "route_id", label: "Route", filter: true },
                    { key: "status", label: "Status", filter: true, render: (p) => <Pill value={p.status === "on_road" ? "departed" : p.status === "hv_in_cage" ? "staging" : "ready"} label={p.status.replace(/^hv_/, "").replace(/_/g, " ")} /> },
                    { key: "custody_scans", label: "Custody scans", num: true },
                    { key: "location", label: "Location", value: (p) => p.location ?? "—" },
                    { key: "cage_minutes", label: "In cage (min)", num: true, value: (p) => p.cage_minutes ?? "—" },
                  ]}
                  rows={hv.packages}
                  rowKey={(p) => p.tracking_id}
                />
              </Card>
            </div>
          );
        }}
      </LiveGate>
    </div>
  );
}
