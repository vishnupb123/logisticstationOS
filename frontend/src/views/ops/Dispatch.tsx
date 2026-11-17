// Dispatch & DSP coordination window (live): DSP performance and standby
// capacity, every driver's state and projected check-in, one-click
// coordination (notify, move route to a later wave, send a standby, remind to
// swipe to finish), sector-wide traffic rerouting, and the live map.
// Drivers and the map are simulated; nothing here contacts a real driver.
import { useState } from "react";
import { type DriverRow, type DspRow, type LiveState, pctv } from "../../api/runtime";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { DriverMap } from "../../components/DriverMap";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";
import { NotificationList } from "../../components/Notifications";
import type { YardRow } from "../../api/runtime";

export function Dispatch() {
  return (
    <div>
      <PageHeader eyebrow="Outbound" title="Dispatch & DSP Coordination" badges={<DataSourceBadge kind="simulated" />}>
        Coordinate delivery service partners and their drivers: who is late, who hasn't left, who has returned but not
        swiped to finish — and act. OTD is measured against the current plan and against the original wave plan.
      </PageHeader>
      <LiveGate>{(s) => <Body s={s} />}</LiveGate>
    </div>
  );
}

const DTABS = [
  { key: "drivers", label: "Drivers & live map" },
  { key: "yard", label: "Yard · VSA" },
  { key: "comms", label: "DSP comms" },
] as const;

function Body({ s }: { s: LiveState }) {
  const [tab, setTab] = useState<(typeof DTABS)[number]["key"]>("drivers");
  return (
    <div className="stack">
      <Tabs tabs={DTABS} value={tab} onChange={(t) => setTab(t as typeof tab)} />
      {tab === "drivers" ? <Drivers s={s} /> : tab === "yard" ? <Yard s={s} /> : <Comms s={s} />}
    </div>
  );
}

function Yard({ s }: { s: LiveState }) {
  const y = s.views.yard;
  const cols: Column<YardRow>[] = [
    { key: "route_id", label: "Route", filter: true },
    { key: "driver_id", label: "Driver" },
    { key: "dsp", label: "DSP", filter: true },
    { key: "checked_in", label: "Checked in", value: (r) => r.checked_in ?? "—" },
    { key: "wait_minutes", label: "VSA wait", num: true, render: (r) => (r.wait_minutes ? `${r.wait_minutes} min` : "—") },
    {
      key: "result",
      label: "VSA result",
      filter: true,
      value: (r) => r.result ?? "—",
      render: (r) =>
        r.result ? (
          <Pill value={r.result === "pass" ? "finished" : r.result === "grounded" ? "cancelled" : r.result === "in_progress" ? "loading" : "staging"} label={r.result.replace(/_/g, " ")} />
        ) : (
          "—"
        ),
    },
    { key: "defect", label: "Defect", value: (r) => r.defect ?? "—" },
    { key: "van_request", label: "Replacement", value: (r) => (r.van_request ? `${r.van_request} · ETA ${r.van_eta}` : "—") },
    {
      key: "act",
      label: "Follow-up",
      render: (r) =>
        r.state === "grounded" && !r.van_request ? (
          <ActButton action={{ kind: "request_replacement_van", target: r.route_id }} label="Request van" variant="primary" testId={`van-${r.route_id}`} />
        ) : r.state === "grounded" ? (
          <span className="muted">grounded {r.grounded_for} min · van coming</span>
        ) : null,
    },
  ];
  return (
    <div className="stack" data-testid="yard-tab">
      <StatRow>
        <Stat label="Yard marshals" value={y.marshals} sub={y.extra_marshals ? `+${y.extra_marshals} assigned` : undefined} />
        <Stat label="VSA queue" value={y.queue} sub={`booked ${y.booked_ahead_minutes} min ahead`} />
        <Stat label="Audited" value={y.audited} />
        <Stat label="Passed" value={y.passed} />
        <Stat label="Fixed on site" value={y.minor_fixed} />
        <Stat label="Grounded" value={y.grounded} sub={y.grounded_now ? <span className="late">{y.grounded_now} waiting now</span> : undefined} />
      </StatRow>
      <div className="toolbar-inline">
        <ActButton action={{ kind: "add_yard_marshal" }} label="Assign an extra yard marshal" />
        <span className="muted" style={{ fontSize: 12 }}>
          Spare vans: {Object.entries(y.spare_vans).map(([k, v]) => `${k.replace("DSP-", "")} ${v}`).join(" · ")}
        </span>
      </div>
      <p className="muted" style={{ fontSize: 13 }}>
        Yard marshals audit every van before it loads. A minor defect (wiper, tyre pressure) is fixed on site; a
        critical one grounds the van: the DSP is told, the van is taken out of service, and a replacement comes from
        the DSP's spare vans, another DSP, or a rental. By default the DSP requests one 20 minutes after grounding.
      </p>
      <Card title="Vehicle safety audits">
        <DataTable testId="vsa-table" columns={cols} rows={y.rows} rowKey={(r) => r.driver_id} rowClass={(r) => (r.state === "grounded" ? "row-risk" : r.result === "minor_fixed" ? "row-warn" : undefined)} empty="No vans have checked in yet." maxHeight={520} />
      </Card>
    </div>
  );
}

function Comms({ s }: { s: LiveState }) {
  return (
    <Card title="Messages to DSPs and drivers (simulated)">
      <NotificationList items={s.views.notifications.items} audience="dsp" />
    </Card>
  );
}

function Drivers({ s }: { s: LiveState }) {
  const d = s.views.dispatch;
  const m = s.snapshot.metrics;
  const [sel, setSel] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "attention" | "on_road" | "returned">("attention");
  const late = d.drivers.filter((x) => (x.late_by ?? 0) > 0 && (x.state === "off_duty" || x.state === "en_route"));
  const noshow = d.drivers.filter((x) => x.no_show_suspected);
  const pendingSwipe = d.drivers.filter((x) => x.state === "pending_swipe");
  const shown = d.drivers.filter((x) =>
    filter === "all"
      ? true
      : filter === "attention"
        ? (((x.late_by ?? 0) > 0 && ["off_duty", "en_route", "checked_in", "loading"].includes(x.state)) ||
          x.no_show_suspected ||
          x.state === "grounded" ||
          x.state === "pending_swipe" ||
          x.driver_id === sel)
        : filter === "on_road"
          ? x.state === "on_road"
          : x.state === "pending_swipe" || x.state === "finished",
  );
  const dspCols: Column<DspRow>[] = [
    { key: "dsp", label: "DSP" },
    { key: "routes", label: "Routes", num: true },
    { key: "departed", label: "Departed", num: true },
    { key: "otd", label: "OTD", num: true, render: (r) => pctv(r.otd) },
    { key: "checked_in", label: "Checked in", num: true },
    { key: "en_route", label: "En route", num: true },
    { key: "late", label: "Late", num: true },
    { key: "no_show_suspected", label: "No-show?", num: true },
    { key: "pending_swipe", label: "Pending swipe", num: true },
    { key: "standby_remaining", label: "Standby left", num: true },
  ];
  const drvCols: Column<DriverRow>[] = [
    { key: "driver_id", label: "Driver", filter: true },
    { key: "dsp", label: "DSP", filter: true },
    { key: "route_id", label: "Route", filter: true },
    { key: "state", label: "State", filter: true, render: (x) => <Pill value={x.no_show_suspected ? "no_show" : x.state} label={x.no_show_suspected ? "no-show?" : x.state.replace(/_/g, " ")} /> },
    { key: "check_in_due", label: "Check-in due" },
    { key: "expected_check_in", label: "Expected / actual", value: (x) => x.checked_in_at ?? x.expected_check_in ?? "—" },
    { key: "late_by", label: "Late by", num: true, render: (x) => ((x.late_by ?? 0) > 0 ? <strong className="late">{x.late_by?.toFixed(0)} min</strong> : "—") },
    { key: "notified", label: "Notified", render: (x) => (x.notified ? "✓" : "—") },
    { key: "stops", label: "Stops", num: true, value: (x) => (x.state === "on_road" || x.state === "pending_swipe" || x.state === "finished" ? `${x.stops_done}/${x.stops_total}` : "—") },
    {
      key: "act",
      label: "Coordinate",
      render: (x) => (
        <span className="act">
          {(x.state === "off_duty" || x.state === "en_route") && !x.notified && (
            <ActButton action={{ kind: "notify_drivers", target: x.route_id }} label="Notify" testId={`notify-${x.route_id}`} />
          )}
          {(x.state === "off_duty" || x.state === "en_route") && (
            <>
              <ActButton action={{ kind: "move_route_wave", target: x.route_id, amount: 1 }} label="Next wave" />
              <ActButton action={{ kind: "reassign_standby", target: x.route_id }} label="Standby" />
            </>
          )}
          {x.state === "pending_swipe" && <ActButton action={{ kind: "notify_swipe_finish" }} label="Remind swipe" />}
          {x.state === "grounded" && !x.van_request && (
            <ActButton action={{ kind: "request_replacement_van", target: x.route_id }} label="Replacement van" variant="primary" />
          )}
          {x.state === "grounded" && x.van_request && <span className="muted">van ETA {x.van_eta}</span>}
        </span>
      ),
    },
  ];
  return (
    <div className="stack">
      <StatRow>
        <Stat label="OTD (current plan)" value={pctv(m.otd.value)} sub={`target ${pctv(m.otd.target)}`} />
        <Stat label="OTD (original plan)" value={pctv(m.otd_original_plan.value)} />
        <Stat label="Late drivers" value={late.length} />
        <Stat label="Suspected no-shows" value={noshow.length} />
        <Stat label="On road" value={d.drivers.filter((x) => x.state === "on_road").length} />
        <Stat label="Pending swipe" value={pendingSwipe.length} sub={`swipe compliance ${pctv(m.swipe_compliance.value)}`} />
      </StatRow>
      <div className="toolbar-inline">
        <ActButton action={{ kind: "notify_drivers", target: "late" }} label="Notify all late drivers" variant="primary" testId="notify-late" />
        <ActButton action={{ kind: "notify_drivers", target: "all" }} label="Wave reminder to everyone" />
        <ActButton action={{ kind: "notify_swipe_finish" }} label="Remind returned drivers to swipe" />
        {(["N", "E", "S", "W"] as const).map((sec) => (
          <ActButton key={sec} action={{ kind: "notify_drivers", params: { sector: sec, leave_early_minutes: 15 } }} label={`Reroute sector ${sec}`} />
        ))}
      </div>
      <Card title="Delivery service partners">
        <DataTable testId="dsp-table" columns={dspCols} rows={d.dsps} rowKey={(r) => r.dsp} maxHeight={240} />
      </Card>
      <div className="grid-2">
        <Card
          title="Drivers"
          actions={
            <div className="seg">
              {(["attention", "on_road", "returned", "all"] as const).map((f) => (
                <button key={f} aria-pressed={filter === f} onClick={() => setFilter(f)}>
                  {f.replace("_", " ")}
                </button>
              ))}
            </div>
          }
        >
          <DataTable
            testId="driver-table"
            columns={drvCols}
            rows={shown}
            rowKey={(x) => x.driver_id}
            rowClass={(x) => (x.no_show_suspected ? "row-risk" : (x.late_by ?? 0) > 0 ? "row-warn" : undefined)}
            empty="No drivers need attention right now."
            maxHeight={520}
          />
        </Card>
        <Card title="Live map (fictional delivery area)">
          <DriverMap map={d.map} drivers={d.drivers} selected={sel} onSelect={(x) => setSel(x.driver_id)} />
          {sel && (
            <p className="muted" style={{ fontSize: 12 }}>
              Selected {sel} — shown in the driver list under “attention”.
            </p>
          )}
        </Card>
      </div>
      <Card title="Dispatch log">
        <ul className="cc-iv-list" data-testid="dispatch-log">
          {s.views.events
            .filter((e) => e.kind === "dispatch" || (e.kind === "action" && /driver|route|wave|standby|swipe/.test(e.message)))
            .slice(-15)
            .reverse()
            .map((e, i) => (
              <li key={i}>
                <span className="tabular">{e.clock}</span> {e.message} {e.source && <span className="muted">({e.source})</span>}
              </li>
            ))}
        </ul>
      </Card>
    </div>
  );
}
