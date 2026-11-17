// Receive (HANDOFF_V2 E3): overall receive status per cycle (predicted
// dispatch vs. container-planned vs. arrived; planned vs. unplanned status
// ladder), and the linehaul board (Arrived / Incoming) with one group-by
// control that splits volume per group value, unload sequence, and a trip
// drawer (legs timeline, assets, issues, watch toggle, containers).
import { useState } from "react";
import { Link } from "react-router-dom";
import type { LiveState } from "../../api/runtime";
import type { GroupByKey, LinehaulV2, StatusLadder } from "../../api/runtimeV2";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { DataUpdated } from "../../components/DataUpdated";
import { GroupBy } from "../../components/GroupBy";
import { PageHeader } from "../../components/PageHeader";
import { Drawer } from "../../components/StatusTree";
import { ActButton, LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";

const CYCLES = ["CYCLE_1", "High_Value"] as const;
type CycleKey = (typeof CYCLES)[number];

const GROUP_LABEL: Record<GroupByKey, string> = {
  none: "None",
  package_size: "Package size",
  destination: "Destination",
  station_ead: "Station EAD",
  cycle: "Cycle",
  cluster: "Cluster",
};

const LADDER: { key: keyof StatusLadder; label: string }[] = [
  { key: "manifested", label: "Manifested" },
  { key: "in_transit", label: "In transit" },
  { key: "arrived", label: "Arrived" },
  { key: "marked_for_reprocess", label: "Marked for reprocess" },
  { key: "inducted", label: "Inducted" },
  { key: "stow_buffered", label: "Stow buffered" },
  { key: "stowed", label: "Stowed" },
  { key: "sidelined", label: "Sidelined" },
];

const STATUS_TONE: Record<LinehaulV2["status"], string> = {
  Arrived: "arrived",
  "In Yard": "in_yard",
  "In-Transit": "en_route",
  "Pending Depart": "planned",
  Cancelled: "cancelled",
};

export function TripStatus({ status }: { status: LinehaulV2["status"] }) {
  return <Pill value={STATUS_TONE[status] ?? "neutral"} label={status} />;
}

export function Inbound() {
  const [tab, setTab] = useState<"Overall status" | "Linehauls">("Overall status");
  return (
    <div>
      <PageHeader eyebrow="Inbound" title="Receive" badges={<DataSourceBadge kind="simulated" />}>
        Status, cycle and volume of containers and packages in the receive process. Ferry delays come from the
        truckfile's progressive ETA revisions — <Link to="/closeout">manage tomorrow's truckfile</Link>.
      </PageHeader>
      <Tabs tabs={["Overall status", "Linehauls"] as const} value={tab} onChange={setTab} />
      <LiveGate>{(s) => (tab === "Overall status" ? <Overall s={s} /> : <Linehauls s={s} />)}</LiveGate>
    </div>
  );
}

function Overall({ s }: { s: LiveState }) {
  const [cycle, setCycle] = useState<CycleKey>("CYCLE_1");
  const c = s.views.receive_v2.cycles[cycle];
  const r = s.views.receive;
  const n = (v: number | undefined) => (v ?? 0).toLocaleString();
  return (
    <div className="stack">
      <div className="toolbar-inline">
        <span className="muted" style={{ fontSize: 12 }}>
          Cycle
        </span>
        <div className="seg" role="group" aria-label="Cycle">
          {CYCLES.map((k) => (
            <button key={k} aria-pressed={cycle === k} onClick={() => setCycle(k)}>
              {k}
            </button>
          ))}
        </div>
      </div>
      <div className="grid-2">
        <Card title={`${cycle} — container planned volume`}>
          <table data-testid="receive-overall" className="ladder">
            <tbody>
              <tr>
                <td>
                  <strong>Predicted dispatch</strong>
                  <div className="muted" style={{ fontSize: 11 }}>
                    Forecast of packages dispatching for the cycle (proposed σ)
                  </div>
                </td>
                <td className="num tabular">{n(c.predicted_dispatch)}</td>
              </tr>
              <tr className="recv-head">
                <td colSpan={2}>
                  <span className="muted">Container planned volume</span>
                </td>
              </tr>
              <tr>
                <td>Current cycle planned</td>
                <td className="num tabular">{n(c.current_cycle_planned)}</td>
              </tr>
              <tr>
                <td>Current cycle arrived</td>
                <td className="num tabular">{n(c.current_cycle_arrived)}</td>
              </tr>
              <tr>
                <td>Other / unplanned arrived</td>
                <td className="num tabular">{n(c.other_unplanned_arrived)}</td>
              </tr>
              <tr>
                <td>
                  <strong>Total arrived</strong>
                </td>
                <td className="num tabular">
                  <strong>{n(c.total_arrived)}</strong>
                </td>
              </tr>
            </tbody>
          </table>
          <DataUpdated clock={s.snapshot.clock} />
        </Card>
        <Card title="Current status — planned vs. unplanned">
          <div className="table-scroll">
            <table data-testid="receive-ladder" className="ladder">
              <thead>
                <tr>
                  <th>Status</th>
                  <th className="num">Planned</th>
                  <th className="num">Unplanned</th>
                  <th className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {LADDER.map((l) => (
                  <tr key={l.key}>
                    <td>{l.label}</td>
                    <td className="num tabular">{n(c.planned[l.key])}</td>
                    <td className="num tabular">{n(c.unplanned[l.key])}</td>
                    <td className="num tabular">{n((c.planned[l.key] ?? 0) + (c.unplanned[l.key] ?? 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <DataUpdated clock={s.snapshot.clock} />
        </Card>
      </div>
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
          {s.snapshot.inbound.trips_in_yard} trailer(s) waiting in the yard · {s.snapshot.inbound.trips_arrived}/
          {s.snapshot.inbound.trips_planned} unloaded.
        </p>
      </Card>
    </div>
  );
}

function Linehauls({ s }: { s: LiveState }) {
  const rv = s.views.receive_v2;
  const [group, setGroup] = useState<GroupByKey>("none");
  const [tripId, setTripId] = useState<string | null>(null);
  const trips = rv.linehauls;
  const values =
    group === "none"
      ? []
      : [...new Set(trips.flatMap((t) => Object.keys(t.group?.[group] ?? {})))].sort((a, b) => a.localeCompare(b));

  const cols: Column<LinehaulV2>[] = [
    {
      key: "trip_id",
      label: "Trip",
      filter: true,
      render: (t) => (
        <button className="trip-link" onClick={() => setTripId(t.trip_id)} data-testid={`trip-${t.trip_id}`}>
          {t.trip_id}
        </button>
      ),
    },
    { key: "origin", label: "Origin", filter: true },
    { key: "status", label: "Status", render: (t) => <TripStatus status={t.status} /> },
    { key: "location", label: "Location", value: (t) => t.location ?? (t.status === "In-Transit" ? "On road" : "—") },
    { key: "planned", label: "Planned" },
    { key: "actual", label: "Actual / ETA", value: (t) => t.actual ?? `ETA ${t.eta}` },
    ...(group === "none"
      ? [{ key: "volume", label: "Volume", num: true, value: (t: LinehaulV2) => t.volume ?? "—" } as Column<LinehaulV2>]
      : values.map(
          (v) =>
            ({
              key: `vol:${v}`,
              label: `Volume · ${v}`,
              num: true,
              value: (t: LinehaulV2) => t.group?.[group]?.[v] ?? 0,
            }) as Column<LinehaulV2>,
        )),
    { key: "unload_sequence", label: "Unload seq.", num: true, value: (t) => t.unload_sequence ?? "—" },
    {
      key: "flags",
      label: "Notes",
      render: (t) => (
        <>
          {t.via_ferry && <Pill value="neutral" label="Ferry" />} {t.issues.length > 0 && <Pill value="planned" label={`${t.issues.length} issue`} />}{" "}
          {t.watched && <Pill value="en_route" label="Watched" />}
        </>
      ),
    },
    {
      key: "act",
      label: "",
      render: (t) =>
        t.status === "In-Transit" || t.status === "In Yard" ? (
          <ActButton action={{ kind: "resequence_unload", target: t.trip_id }} label="Unload first" />
        ) : null,
    },
  ];
  const arrived = trips.filter((t) => t.status === "Arrived" || t.status === "In Yard");
  const incoming = trips.filter((t) => !(t.status === "Arrived" || t.status === "In Yard"));
  const trip = trips.find((t) => t.trip_id === tripId) ?? null;
  return (
    <div className="stack">
      <StatRow>
        <Stat label="Arrived / in yard" value={arrived.length} />
        <Stat label="Incoming" value={incoming.length} />
        <Stat label="Watch list" value={rv.watch.length} sub={rv.watch.join(", ") || "none"} />
        <Stat label="With issues" value={trips.filter((t) => t.issues.length).length} />
      </StatRow>
      <Card
        title="Linehauls"
        actions={
          <GroupBy
            name="linehaul-group"
            options={rv.group_by.map((k) => ({ key: k, label: GROUP_LABEL[k] ?? k }))}
            value={group}
            onChange={setGroup}
          />
        }
      >
        <h3 className="page-section-title">Arrived ({arrived.length})</h3>
        <DataTable testId="linehaul-arrived" columns={cols} rows={arrived} rowKey={(t) => t.trip_id} maxHeight={360} empty="No trailers have arrived yet." />
        <h3 className="page-section-title">Incoming ({incoming.length})</h3>
        <DataTable
          testId="linehaul-incoming"
          columns={cols}
          rows={incoming}
          rowKey={(t) => t.trip_id}
          maxHeight={360}
          empty="No more linehauls planned for this cycle."
          rowClass={(t) => (t.issues.length ? "row-warn" : undefined)}
        />
        <p className="muted" style={{ fontSize: 12 }}>
          Volume fills in as manifests arrive. {group !== "none" && `Split by ${GROUP_LABEL[group].toLowerCase()} — each row's split sums to its volume.`}
        </p>
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
      {trip && <TripDrawer trip={trip} onClose={() => setTripId(null)} />}
    </div>
  );
}

function TripDrawer({ trip, onClose }: { trip: LinehaulV2; onClose: () => void }) {
  const pending = trip.containers.reduce((a, c) => a + c.pending_induct, 0);
  const total = trip.containers.reduce((a, c) => a + c.total, 0);
  return (
    <Drawer title={`Trip ${trip.trip_id}`} onClose={onClose} testId="trip-drawer">
      <div className="toolbar-inline">
        <TripStatus status={trip.status} />
        {trip.watched && <Pill value="en_route" label="On watch list" />}
        <ActButton
          action={{ kind: "watch_trip", target: trip.trip_id }}
          label={trip.watched ? "Remove from watch list" : "Add to watch list"}
          testId="watch-trip"
        />
      </div>
      <dl className="kv">
        <dt>Origin</dt>
        <dd>{trip.origin}</dd>
        <dt>Operator type</dt>
        <dd>{trip.operator_type === "team" ? "Team drivers" : "Single driver"}</dd>
        <dt>Tractor / trailer</dt>
        <dd>
          {trip.tractor ?? "—"} / {trip.trailer ?? "—"}
        </dd>
        <dt>Planned / actual</dt>
        <dd>
          {trip.planned} / {trip.actual ?? `ETA ${trip.eta}`}
        </dd>
        <dt>Location</dt>
        <dd>{trip.location ?? (trip.status === "In-Transit" ? "On road" : "—")}</dd>
        <dt>Volume</dt>
        <dd>
          {trip.volume?.toLocaleString() ?? "—"} · {(trip.unplanned_share * 100).toFixed(0)}% unplanned
        </dd>
      </dl>
      <h3 className="page-section-title">Legs</h3>
      <ol className="legs" data-testid="trip-legs">
        {trip.legs.map((l, i) => (
          <li key={i} className={`legs--${l.state}`}>
            <strong>
              {l.from} → {l.to}
            </strong>{" "}
            <Pill value={l.mode === "ferry" ? "planned" : "neutral"} label={l.mode === "ferry" ? "Ferry" : "Road"} />{" "}
            <span className="muted">{l.state === "done" ? "Done" : l.state === "active" ? "In progress" : "Planned"}</span>
            <div className="muted tabular" style={{ fontSize: 12 }}>
              Planned {l.planned_depart_clock} → {l.planned_arrive_clock}
              {l.eta_clock !== l.planned_arrive_clock && ` · ETA ${l.eta_clock}`}
            </div>
          </li>
        ))}
      </ol>
      <h3 className="page-section-title">Issues ({trip.issues.length})</h3>
      {trip.issues.length === 0 ? (
        <p className="muted">No issues reported for this trip.</p>
      ) : (
        <ul>
          {trip.issues.map((x, i) => (
            <li key={i}>
              <Pill value="planned" label={x.kind.replace(/_/g, " ")} /> {x.text}
            </li>
          ))}
        </ul>
      )}
      <h3 className="page-section-title">
        Containers — {pending.toLocaleString()} pending induct / {total.toLocaleString()} total
      </h3>
      <DataTable
        testId="trip-containers"
        columns={[
          { key: "id", label: "Container" },
          { key: "type", label: "Type" },
          { key: "pending_induct", label: "Pending induct / total", num: true, render: (c) => `${c.pending_induct} / ${c.total}` },
        ]}
        rows={trip.containers}
        rowKey={(c) => c.id}
        maxHeight={260}
        empty="Containers appear when the manifest arrives."
      />
      <p className="muted" style={{ fontSize: 11 }}>
        Synthetic trip; ETA revisions come only from the ferry provider or a check.
      </p>
    </Drawer>
  );
}
