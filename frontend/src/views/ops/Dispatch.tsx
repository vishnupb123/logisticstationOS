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
import { ActButton, LiveGate, Pill, Stat, StatRow } from "../../components/live";

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

function Body({ s }: { s: LiveState }) {
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
