// Station & resources (live layout, sort-path partitions, devices) and the
// unified Work Items inbox (HANDOFF_V2 E10).
import { useState } from "react";
import { Card } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";
import { WorkItemInbox } from "../../components/WorkItemInbox";

const CATEGORIES = ["Induct", "Sort", "Pick & Stage", "Dispatch", "Fleet", "Safety", "Ops Updates", "People"];
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
        One inbox for everything the simulated station needs a person to do — notifications, close-out tasks, scrubs and
        reviews, and agent recommendations awaiting approval — with an expiring-in countdown on the simulated clock.
      </PageHeader>
      <LiveGate>
        {(s) => {
          const w = s.views.work_items_v2;
          const sm = w.summary;
          return (
            <div className="stack">
              <StatRow>
                <Stat label="Pending tasks" value={<span data-testid="wi-pending">{sm.pending}</span>} />
                <Stat label="High priority" value={sm.high_priority} sub={sm.high_priority ? "act first" : undefined} />
                <Stat label="Completed today" value={<span data-testid="wi-completed">{sm.completed_today}</span>} />
                <Stat label="Expired today" value={sm.expired_today} sub={sm.dismissed_today ? `${sm.dismissed_today} dismissed` : undefined} />
                <Stat label="Carried over" value={sm.carried_over} sub="from previous days" />
                {sm.agent_recommendations !== undefined && <Stat label="Agent recommendations" value={sm.agent_recommendations} sub="today" />}
              </StatRow>
              <Card title="Pending by category">
                <StatRow>
                  {CATEGORIES.map((c) => (
                    <Stat key={c} label={c} value={sm.by_category[c] ?? 0} />
                  ))}
                </StatRow>
              </Card>
              <Card title="Work item inbox">
                <WorkItemInbox items={w.items} />
              </Card>
            </div>
          );
        }}
      </LiveGate>
    </div>
  );
}
