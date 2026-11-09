// Receive: overall receive status for the cycle (planned vs. unplanned,
// manifested vs. unplanned-manifested, in transit / yard / reprocess) and
// the linehaul board (planned vs. actual, door, unload sequence, ferry ETA
// revisions) with group-by and unload resequencing.
import { useState } from "react";
import { Link } from "react-router-dom";
import type { LiveState, Trip } from "../../api/runtime";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Tabs } from "../../components/live";

const GROUPS = ["None", "Origin", "Status", "Ferry"] as const;

export function Inbound() {
  const [tab, setTab] = useState<"Overall status" | "Linehauls">("Overall status");
  return (
    <div>
      <PageHeader eyebrow="Inbound" title="Receive" badges={<DataSourceBadge kind="simulated" />}>
        Status, cycle and volume of containers and packages in the receive process. Ferry delays come from the
        truckfile's progressive ETA revisions — <Link to="/truckfile">manage the truckfile</Link>.
      </PageHeader>
      <Tabs tabs={["Overall status", "Linehauls"] as const} value={tab} onChange={setTab} />
      <LiveGate>{(s) => (tab === "Overall status" ? <Overall s={s} /> : <Linehauls s={s} />)}</LiveGate>
    </div>
  );
}

function Row({ label, value, head }: { label: string; value?: number; head?: boolean }) {
  return (
    <tr className={head ? "recv-head" : undefined}>
      <td>{head ? <span className="muted">{label}</span> : <strong>{label}</strong>}</td>
      <td className="num tabular">{head ? "" : (value ?? 0).toLocaleString()}</td>
    </tr>
  );
}

function Overall({ s }: { s: LiveState }) {
  const r = s.views.receive;
  return (
    <div className="grid-2">
      <Card title={`Cycle ${s.snapshot.cycle.name} — packages`}>
        <table data-testid="receive-overall">
          <tbody>
            <Row label="Predicted dispatch" value={r.predicted_dispatch} />
            <Row label="Container planned volume" head />
            <Row label="Current cycle planned" value={r.current_cycle_planned} />
            <Row label="Current cycle arrived actual" value={r.current_cycle_arrived} />
            <Row label="Other / unplanned arrived actual" value={r.other_unplanned_arrived} />
            <Row label="Total arrived actual" value={r.total_arrived} />
            <Row label="Current status" head />
            <Row label="Manifested" value={r.manifested} />
            <Row label="Unplanned manifested" value={r.unplanned_manifested} />
            <Row label="In transit" value={r.in_transit} />
            <Row label="Arrived (in yard)" value={r.in_yard} />
            <Row label="Marked for reprocess" value={r.marked_for_reprocess} />
            <Row label="Inducted" value={r.inducted} />
          </tbody>
        </table>
      </Card>
      <Card title="Dock doors">
        <div className="door-grid">
          {r.doors.map((d) => (
            <div key={d.door} className={`door${d.trip ? " door--busy" : ""}`}>
              <div className="muted">DOOR {d.door}</div>
              <strong>{d.trip ?? "free"}</strong>
            </div>
          ))}
        </div>
        <p className="muted" style={{ fontSize: 12 }}>
          {s.snapshot.inbound.trips_in_yard} trailer(s) waiting in the yard ·{" "}
          {s.snapshot.inbound.trips_arrived}/{s.snapshot.inbound.trips_planned} unloaded.
        </p>
      </Card>
    </div>
  );
}

function Linehauls({ s }: { s: LiveState }) {
  const [group, setGroup] = useState<(typeof GROUPS)[number]>("None");
  const trips = s.snapshot.trips;
  const cols: Column<Trip>[] = [
    { key: "trip_id", label: "Trip", filter: true },
    { key: "origin", label: "Origin", filter: true },
    { key: "status", label: "Status", render: (t) => <Pill value={t.status} />, filter: true },
    { key: "door", label: "Location", render: (t) => (t.door ? `DOOR ${t.door}` : t.status === "in_yard" ? "YARD" : "—") },
    { key: "ferry_sailing", label: "Sailing", value: (t) => t.ferry_sailing ?? "—" },
    { key: "planned_arrival", label: "Planned" },
    { key: "eta", label: "ETA / actual", value: (t) => t.actual_arrival ?? t.eta },
    {
      key: "delay_minutes",
      label: "Delay",
      num: true,
      render: (t) =>
        t.delay_minutes ? (
          <span title={t.delay_reason ?? ""}>
            {t.delay_minutes.toFixed(0)} min{t.revision_count > 1 ? ` · rev ${t.revision_count}` : ""}
          </span>
        ) : (
          "—"
        ),
    },
    { key: "volume", label: "Volume", num: true },
    { key: "unload_sequence", label: "Unload seq.", num: true, value: (t) => t.unload_sequence ?? "—" },
    {
      key: "act",
      label: "",
      render: (t) =>
        t.status === "in_transit" || t.status === "in_yard" ? (
          <ActButton action={{ kind: "resequence_unload", target: t.trip_id }} label="Unload first" />
        ) : null,
    },
  ];
  const keyOf = (t: Trip) =>
    group === "Origin" ? t.origin : group === "Status" ? t.status : group === "Ferry" ? (t.via_ferry ? "Ferry" : "Road") : "All";
  const groups = [...new Set(trips.map(keyOf))];
  return (
    <Card
      title="Linehauls"
      actions={
        <div className="seg" role="group" aria-label="Group by">
          {GROUPS.map((g) => (
            <button key={g} aria-pressed={group === g} onClick={() => setGroup(g)}>
              {g}
            </button>
          ))}
        </div>
      }
    >
      {groups.map((g) => (
        <div key={g}>
          {group !== "None" && (
            <h3 className="page-section-title">
              {g.replace(/_/g, " ")} ({trips.filter((t) => keyOf(t) === g).length})
            </h3>
          )}
          <DataTable
            testId="linehaul-table"
            columns={cols}
            rows={trips.filter((t) => keyOf(t) === g)}
            rowKey={(t) => t.trip_id}
            rowClass={(t) => (t.arrives_after_pick_start ? "row-risk" : t.delay_minutes > 0 ? "row-warn" : undefined)}
          />
        </div>
      ))}
    </Card>
  );
}
