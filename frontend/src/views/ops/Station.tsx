// Station & resources (live layout, sort-path partitions, devices) and the
// Work Items queue (tasks generated from live state, each with a one-click
// coordination action where one exists).
import { useState } from "react";
import { Card } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";

const TABS = ["Station layout", "Sort paths", "Devices", "Event log"] as const;

export function StationResources() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Station layout");
  return (
    <div>
      <PageHeader eyebrow="Station management" title="Station & Resources" badges={<DataSourceBadge kind="simulated" />}>
        Station NOVA-1 (fictional) — layout, cycle partitions / sort-path allocation, and device health, all live.
      </PageHeader>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      <LiveGate>
        {(s) => {
          if (tab === "Station layout") {
            const l = s.views.layout;
            return (
              <div className="stack">
                <div className="grid-2">
                  <Card title="Induct lines">
                    <div className="toolbar-inline">
                      {l.lines.map((x) => (
                        <Pill key={x.line} value={x.status} label={`${x.line} · ${x.status}`} />
                      ))}
                    </div>
                  </Card>
                  <Card title="Dock doors">
                    <div className="toolbar-inline">
                      {l.doors.map((d) => (
                        <Pill key={d.door} value={d.trip ? "unloading" : "neutral"} label={`Door ${d.door}: ${d.trip ?? "free"}`} />
                      ))}
                    </div>
                  </Card>
                </div>
                <Card title="Aisles (bay fill)">
                  <div className="cluster-grid" data-testid="layout-aisles">
                    {l.aisles.map((a) => {
                      const f = a.capacity ? a.level / a.capacity : 0;
                      return (
                        <div key={a.aisle} className="cluster-cell" title={`${a.level}/${a.capacity}`} style={{ background: `color-mix(in srgb, var(--series-1) ${Math.round(f * 70)}%, var(--surface-1))`, color: f > 0.6 ? "#fff" : undefined }}>
                          {a.aisle}
                        </div>
                      );
                    })}
                  </div>
                </Card>
                <Card title="Staging locations">
                  <div className="cluster-grid">
                    {l.staging.map((x) => (
                      <div key={x.location} className="cluster-cell" title={x.status}>
                        {x.location.replace("STG-", "")}
                        <br />
                        <Pill value={x.status} label={x.status.replace("_", " ")} />
                      </div>
                    ))}
                  </div>
                </Card>
              </div>
            );
          }
          if (tab === "Sort paths") {
            return (
              <Card title="System-generated grid allocation">
                <DataTable
                  testId="sort-paths"
                  columns={[
                    { key: "partition", label: "Partition" },
                    { key: "cycle", label: "Cycle" },
                    { key: "grid", label: "Grid" },
                    { key: "overlaps", label: "Grid overlaps", value: (r) => r.overlaps.join(", ") || "—" },
                  ]}
                  rows={s.views.sort_paths}
                  rowKey={(r) => r.partition}
                />
              </Card>
            );
          }
          if (tab === "Devices") {
            const dv = s.views.devices;
            return (
              <div className="stack">
                <StatRow>
                  <Stat label="Handhelds online" value={dv.handhelds.length} />
                  <Stat label="Low battery" value={dv.handhelds.filter((h) => h.status === "low_battery").length} />
                  <Stat label="Scanners degraded" value={dv.scanners.filter((x) => x.status !== "online").length} />
                </StatRow>
                <div className="grid-2">
                  <Card title="Induct scanners">
                    <DataTable columns={[{ key: "device", label: "Device" }, { key: "read_rate", label: "Read rate", num: true, value: (x) => `${(x.read_rate * 100).toFixed(2)}%` }, { key: "status", label: "Status", render: (x) => <Pill value={x.status} /> }]} rows={dv.scanners} rowKey={(x) => x.device} maxHeight={260} />
                  </Card>
                  <Card title="Handhelds">
                    <DataTable testId="devices-table" columns={[{ key: "device", label: "Device", filter: true }, { key: "assigned_to", label: "Assigned to", filter: true }, { key: "battery", label: "Battery", num: true, value: (x) => `${x.battery}%` }, { key: "status", label: "Status", render: (x) => <Pill value={x.status} /> }]} rows={dv.handhelds} rowKey={(x) => x.device} maxHeight={420} />
                  </Card>
                </div>
              </div>
            );
          }
          return (
            <Card title="Station event log">
              <DataTable
                testId="event-log"
                columns={[
                  { key: "clock", label: "Time" },
                  { key: "kind", label: "Kind", filter: true, render: (e) => <Pill value={e.kind === "disruption" ? "down" : e.kind === "action" ? "running" : "neutral"} label={e.kind} /> },
                  { key: "message", label: "Event", filter: true },
                  { key: "source", label: "Source", filter: true, value: (e) => e.source ?? "—" },
                ]}
                rows={[...s.views.events].reverse().map((e, i) => ({ ...e, _k: i }))}
                rowKey={(e) => String(e._k)}
                maxHeight={640}
              />
            </Card>
          );
        }}
      </LiveGate>
    </div>
  );
}

export function WorkItems() {
  return (
    <div>
      <PageHeader eyebrow="Operate" title="Work Items" badges={<DataSourceBadge kind="simulated" />}>
        Tasks raised from the live station state — each with a one-click coordination action where one exists.
      </PageHeader>
      <LiveGate>
        {(s) => (
          <Card title={`${s.views.work_items.length} open item(s)`}>
            {s.views.work_items.length === 0 ? (
              <p className="muted">Nothing needs attention right now.</p>
            ) : (
              <ul className="work-items" data-testid="work-items">
                {s.views.work_items.map((w, i) => (
                  <li key={i}>
                    <Pill value={w.priority === "high" ? "down" : "ready"} label={w.priority} />
                    <span className="muted">{w.area}</span>
                    <span className="work-items__title">{w.title}</span>
                    {w.action && <ActButton action={w.action} label="Do it" />}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
      </LiveGate>
    </div>
  );
}
