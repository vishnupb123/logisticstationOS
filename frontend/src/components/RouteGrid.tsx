// Outbound route grid: one row per stage-by wave, one cell per route,
// colored by route status (categorical identity, fixed slot per status —
// never cycled), with an at-risk outline. A legend is always present and
// every cell has a text tooltip, so status never depends on color alone.
import type { RouteRow } from "../api/stationOps";
import "./RouteGrid.css";

const STATUS: { key: RouteRow["status"]; label: string; slot: number }[] = [
  { key: "not_ready", label: "Pending pick", slot: 4 },
  { key: "picking", label: "Picking", slot: 2 },
  { key: "picked", label: "Picked", slot: 7 },
  { key: "staged", label: "Staged", slot: 1 },
  { key: "departed", label: "Departed", slot: 3 },
];
const SLOT = Object.fromEntries(STATUS.map((s) => [s.key, s.slot]));
const LABEL = Object.fromEntries(STATUS.map((s) => [s.key, s.label]));

export function RouteGrid({ routes }: { routes: RouteRow[] }) {
  const waves = new Map<string, RouteRow[]>();
  for (const r of routes) {
    waves.set(r.stage_by, [...(waves.get(r.stage_by) ?? []), r]);
  }
  return (
    <div className="route-grid" data-testid="route-grid">
      <div className="route-grid__legend">
        {STATUS.map((s) => (
          <span key={s.key} className="route-grid__legend-item">
            <span className="route-grid__swatch" style={{ background: `var(--series-${s.slot})` }} />
            {s.label}
          </span>
        ))}
        <span className="route-grid__legend-item">
          <span className="route-grid__swatch route-grid__swatch--risk" />
          At risk (projected late stage)
        </span>
      </div>
      {[...waves.entries()].map(([stageBy, rs]) => (
        <div className="route-grid__row" key={stageBy}>
          <div className="route-grid__wave tabular">{stageBy}</div>
          <div className="route-grid__count tabular">{rs.length}</div>
          <div className="route-grid__cells">
            {rs.map((r) => (
              <span
                key={r.route_id}
                className={"route-grid__cell" + (r.at_risk ? " route-grid__cell--risk" : "")}
                style={{ background: `var(--series-${SLOT[r.status]})` }}
                title={`${r.route_id} · ${LABEL[r.status]} · ${r.dsp} · ${r.staging_location} · stage by ${r.stage_by}${
                  r.projected_stage_at && r.status !== "staged" && r.status !== "departed"
                    ? ` · projected ${r.projected_stage_at}`
                    : ""
                }${r.departed_at ? ` · departed ${r.departed_at}` : ""}${
                  r.depart_late_minutes ? ` (${r.depart_late_minutes.toFixed(0)} min late)` : ""
                }`}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
