// Outbound (live): overview wave grid, Pick (route view + layout grid view,
// filters, SPR thresholds, prioritise / sideline / unsideline), and Stage.
import { useState } from "react";
import { type LiveState, type RouteRow, STATUS_LABEL, pctv } from "../../api/runtime";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow } from "../../components/live";
import "../../components/RouteGrid.css";

const SLOT: Record<RouteRow["status"], number> = {
  not_ready: 8,
  ready: 4,
  picking: 2,
  staging: 5,
  staged: 1,
  loading: 7,
  departed: 3,
};

function WaveGrid({ routes, onPick }: { routes: RouteRow[]; onPick?: (r: RouteRow) => void }) {
  const waves = new Map<string, RouteRow[]>();
  for (const r of routes) waves.set(r.stage_by, [...(waves.get(r.stage_by) ?? []), r]);
  return (
    <div className="route-grid" data-testid="wave-grid">
      <div className="route-grid__legend">
        {(Object.keys(SLOT) as RouteRow["status"][]).map((k) => (
          <span key={k} className="route-grid__legend-item">
            <span className="route-grid__swatch" style={{ background: `var(--series-${SLOT[k]})` }} />
            {STATUS_LABEL[k]}
          </span>
        ))}
        <span className="route-grid__legend-item">
          <span className="route-grid__swatch route-grid__swatch--risk" />
          At risk
        </span>
        <span className="route-grid__legend-item">▲ sidelined · ● late driver</span>
      </div>
      {[...waves.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([stageBy, rs]) => (
          <div className="route-grid__row" key={stageBy}>
            <div className="route-grid__wave tabular">{stageBy}</div>
            <div className="route-grid__count tabular">{rs.length}</div>
            <div className="route-grid__cells">
              {rs.map((r) => (
                <button
                  key={r.route_id}
                  className={"route-grid__cell" + (r.at_risk ? " route-grid__cell--risk" : "")}
                  style={{ background: `var(--series-${SLOT[r.status]})`, border: "none", padding: 0, fontSize: 9, color: "#fff", lineHeight: "14px" }}
                  title={`${r.route_id} · ${STATUS_LABEL[r.status]} · ${r.dsp} · ${r.staging_location} · stage by ${r.stage_by}${r.driver_late_by ? ` · driver +${r.driver_late_by.toFixed(0)}m` : ""}`}
                  onClick={() => onPick?.(r)}
                  aria-label={`${r.route_id} ${STATUS_LABEL[r.status]}`}
                >
                  {r.sidelined ? "▲" : (r.driver_late_by ?? 0) > 0 ? "●" : ""}
                </button>
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}

function routeCols(extra: Column<RouteRow>[] = []): Column<RouteRow>[] {
  return [
    { key: "stage_by", label: "Stage by", filter: true },
    { key: "route_id", label: "Route", filter: true },
    { key: "priority", label: "Priority", num: true, value: (r) => r.priority || "—" },
    {
      key: "status",
      label: "Status",
      filter: true,
      value: (r) => STATUS_LABEL[r.status],
      render: (r) => (
        <>
          <Pill value={r.status} label={STATUS_LABEL[r.status]} />
          {r.sidelined && <Pill value="planned" label="sidelined" />}
          {r.at_risk && <Pill value="down" label="at risk" />}
        </>
      ),
    },
    {
      key: "spr",
      label: "SPR",
      num: true,
      render: (r) => (
        <span className={r.spr_flag === "high" ? "spr-high" : undefined} title="Shipments per route">
          {r.spr}
        </span>
      ),
    },
    { key: "progress", label: "Progress", num: true, value: (r) => `${r.bags_done}/${r.bags_total}` },
    { key: "picker", label: "Associate", filter: true, value: (r) => r.picker ?? "—" },
    { key: "pick_minutes", label: "Duration", num: true, value: (r) => (r.pick_minutes ? `${r.pick_minutes} min` : "—") },
    { key: "dsp", label: "Type", filter: true, value: (r) => `DSP:${r.dsp.replace("DSP-", "")}` },
    ...extra,
  ];
}

export function OutboundOverview() {
  const [view, setView] = useState<"visual" | "table">("visual");
  return (
    <div>
      <PageHeader eyebrow="Outbound" title="Outbound Overview" badges={<DataSourceBadge kind="simulated" />}>
        Every route and its status through pick → stage → load → depart, by stage-by wave.
      </PageHeader>
      <LiveGate>
        {(s) => {
          const o = s.snapshot.outbound;
          return (
            <div className="stack">
              <StatRow>
                <Stat label="Total routes" value={o.routes_total} />
                <Stat label="Not assigned" value={o.ready} />
                <Stat label="Pending stow" value={o.not_ready} />
                <Stat label="Picking" value={o.picking} />
                <Stat label="Pending stage" value={o.staging} />
                <Stat label="Pending depart" value={(o.staged ?? 0) + (o.loading ?? 0)} />
                <Stat label="Departed" value={o.departed} />
                <Stat label="At risk" value={o.at_risk} />
                <Stat label="Late drivers" value={o.drivers_late} />
              </StatRow>
              <Card
                title="Routes by stage-by wave"
                actions={
                  <div className="seg">
                    <button aria-pressed={view === "visual"} onClick={() => setView("visual")}>Visual view</button>
                    <button aria-pressed={view === "table"} onClick={() => setView("table")}>Table view</button>
                  </div>
                }
              >
                {view === "visual" ? <WaveGrid routes={s.snapshot.routes} /> : <DataTable columns={routeCols()} rows={s.snapshot.routes} rowKey={(r) => r.route_id} />}
              </Card>
            </div>
          );
        }}
      </LiveGate>
    </div>
  );
}

export function Pick() {
  const [view, setView] = useState<"route" | "grid">("route");
  const [highSpr, setHighSpr] = useState(false);
  const [atRisk, setAtRisk] = useState(false);
  return (
    <div>
      <PageHeader eyebrow="Outbound" title="Pick" badges={<DataSourceBadge kind="simulated" />}>
        Routes' status and live details during pick. Prioritise, sideline or return routes — the next free picker takes
        the highest-priority ready route.
      </PageHeader>
      <LiveGate>
        {(s) => {
          const p = s.views.pick;
          let rows = s.snapshot.routes;
          if (highSpr) rows = rows.filter((r) => r.spr_flag === "high");
          if (atRisk) rows = rows.filter((r) => r.at_risk);
          const actions: Column<RouteRow> = {
            key: "actions",
            label: "Actions",
            render: (r) =>
              r.status === "not_ready" || r.status === "ready" ? (
                <span className="act">
                  <ActButton action={{ kind: "prioritize_route", target: r.route_id, amount: 1 }} label="Prioritise" testId={`prio-${r.route_id}`} />
                  {r.sidelined ? (
                    <ActButton action={{ kind: "unsideline_route", target: r.route_id }} label="Return" />
                  ) : (
                    <ActButton action={{ kind: "sideline_route", target: r.route_id }} label="Sideline" />
                  )}
                </span>
              ) : null,
          };
          return (
            <div className="stack">
              <StatRow>
                <Stat label="Totals" value={p.total_routes} sub="routes" />
                <Stat label="Avg duration" value={p.avg_pick_minutes ? `${p.avg_pick_minutes}m` : "—"} sub="route / picklist" />
                <Stat label="Not ready" value={p.not_ready} />
                <Stat label="Not assigned" value={p.not_assigned} />
                <Stat label="In progress" value={p.in_progress} />
                <Stat label="Partially picked" value={p.partially_picked} />
                <Stat label="Picked" value={p.picked} />
                <Stat label="Sidelined" value={p.sidelined} />
              </StatRow>
              <div className="toolbar-inline">
                <div className="seg">
                  <button aria-pressed={view === "route"} onClick={() => setView("route")}>Route view</button>
                  <button aria-pressed={view === "grid"} onClick={() => setView("grid")}>Layout grid view</button>
                </div>
                <label style={{ fontSize: 12 }}>
                  <input type="checkbox" checked={highSpr} onChange={(e) => setHighSpr(e.target.checked)} /> High SPR (&gt;270)
                </label>
                <label style={{ fontSize: 12 }}>
                  <input type="checkbox" checked={atRisk} onChange={(e) => setAtRisk(e.target.checked)} /> At risk
                </label>
                <span className="muted" style={{ fontSize: 12 }}>
                  Dispatch plan: {s.session.ofd_date} · {s.snapshot.cycle.name} · pick start {s.snapshot.cycle.pick_start}
                </span>
              </div>
              {view === "route" ? (
                <Card title="Routes">
                  <DataTable testId="pick-table" columns={routeCols([actions])} rows={rows} rowKey={(r) => r.route_id} rowClass={(r) => (r.at_risk ? "row-risk" : undefined)} maxHeight={600} />
                </Card>
              ) : (
                <Card title="Staging layout grid">
                  <StagingGrid s={s} />
                </Card>
              )}
            </div>
          );
        }}
      </LiveGate>
    </div>
  );
}

function StagingGrid({ s }: { s: LiveState }) {
  const byLoc = new Map(s.snapshot.routes.map((r) => [r.staging_location, r]));
  const rows = ["A", "B"];
  return (
    <div className="stack">
      {rows.map((row) => (
        <div key={row}>
          <h3 className="page-section-title">Staging row {row}</h3>
          <div className="cluster-grid">
            {s.views.layout.staging
              .filter((x) => x.location.startsWith(`STG-${row}`))
              .map((x) => {
                const r = byLoc.get(x.location);
                return (
                  <div key={x.location} className="cluster-cell" style={{ background: r ? `color-mix(in srgb, var(--series-${SLOT[r.status]}) 35%, var(--surface-1))` : undefined }} title={r ? `${r.route_id} ${STATUS_LABEL[r.status]}` : x.location}>
                    {x.location.replace("STG-", "")}
                    <br />
                    {r?.route_id}
                  </div>
                );
              })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Stage() {
  return (
    <div>
      <PageHeader eyebrow="Outbound" title="Stage" badges={<DataSourceBadge kind="simulated" />}>
        Routes' staging status: carts staged to their location, high-value handoffs, and the stage-by deadline.
      </PageHeader>
      <LiveGate>
        {(s) => {
          const st = s.views.stage;
          return (
            <div className="stack">
              <StatRow>
                <Stat label="Total routes" value={st.total_routes} />
                <Stat label="Timely staged" value={pctv(st.timely_staged)} />
                <Stat label="Not ready" value={st.not_ready} />
                <Stat label="Partially staged" value={st.partially_staged} />
                <Stat label="Staged" value={st.staged} />
                <Stat label="Departed" value={st.departed} />
              </StatRow>
              <Card title="Routes">
                <DataTable
                  testId="stage-table"
                  columns={[
                    { key: "stage_by", label: "Stage by", filter: true },
                    { key: "route_id", label: "Route", filter: true },
                    { key: "staging_location", label: "Location", filter: true },
                    { key: "status", label: "Status", filter: true, value: (r) => STATUS_LABEL[r.status], render: (r) => <Pill value={r.status} label={STATUS_LABEL[r.status]} /> },
                    { key: "staged_at", label: "Stage time", value: (r) => r.staged_at ?? r.projected_stage_at ?? "—", render: (r) => r.staged_at ?? (r.projected_stage_at ? <span className="muted">proj. {r.projected_stage_at}</span> : "—") },
                    { key: "carts", label: "Carts", num: true, value: (r) => (r.carts ? `${r.carts_staged}/${r.carts}` : "—") },
                    { key: "hv_pending", label: "HV pending", num: true },
                    { key: "dsp", label: "Type", filter: true, value: (r) => `DSP:${r.dsp.replace("DSP-", "")}` },
                  ]}
                  rows={s.snapshot.routes}
                  rowKey={(r) => r.route_id}
                  rowClass={(r) => (r.at_risk ? "row-risk" : r.status === "staging" ? "row-warn" : undefined)}
                  maxHeight={620}
                />
              </Card>
            </div>
          );
        }}
      </LiveGate>
    </div>
  );
}
