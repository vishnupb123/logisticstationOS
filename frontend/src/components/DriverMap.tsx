// Live driver map of a *fictional* delivery area (no real geography): a
// generated street grid, two ring roads, radial highways, a river crossable
// only at bridges, parks and neighbourhoods. Drivers move along the roads —
// home → station for check-in, then out to their zone, stop by stop, and back.
// Selecting a driver draws their road path and delivery stops.
// Uniform scaling (viewBox + xMidYMid meet), so <text> labels don't distort.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { type DriverRow, type Views, runtimeApi } from "../api/runtime";
import "./DriverMap.css";

const STATE_COLOR: Record<string, string> = {
  off_duty: "var(--text-muted)",
  en_route: "var(--series-1)",
  checked_in: "var(--series-7)",
  vsa: "var(--series-7)",
  vsa_fix: "var(--series-4)",
  grounded: "var(--series-8)",
  loading: "var(--series-7)",
  on_road: "var(--series-3)",
  pending_swipe: "var(--series-4)",
  finished: "var(--series-6)",
};
const STATE_LABEL: Record<string, string> = {
  off_duty: "Not yet left",
  en_route: "Driving to station",
  checked_in: "At station / VSA / loading",
  grounded: "Van grounded",
  on_road: "On route",
  pending_swipe: "Returned, not swiped",
  finished: "Finished",
};
const SECTOR_RECT: Record<string, [number, number, number, number]> = {
  N: [-26, -26, 52, 18],
  S: [-26, 8, 52, 18],
  W: [-26, -26, 18, 52],
  E: [8, -26, 18, 52],
};

const pts = (p: [number, number][]) => p.map(([x, y]) => `${x},${-y}`).join(" ");

export function DriverMap({
  map,
  drivers,
  selected,
  onSelect,
  height = 520,
}: {
  map: Views["dispatch"]["map"];
  drivers: DriverRow[];
  selected?: string | null;
  onSelect?: (d: DriverRow) => void;
  height?: number;
}) {
  const city = useQuery({ queryKey: ["city-map"], queryFn: runtimeApi.map, staleTime: Infinity });
  const sel = drivers.find((d) => d.driver_id === selected);
  const path = useQuery({
    queryKey: ["driver-path", selected, sel?.state],
    queryFn: () => runtimeApi.driverPath(selected as string),
    enabled: !!selected,
    refetchInterval: 15000,
  });
  const [zoom, setZoom] = useState(1);
  const e = map.extent_km / zoom;
  const c = city.data;
  const focus = zoom > 1 && sel ? [sel.x, -sel.y] : [0, 0];
  const p = path.data;
  return (
    <div className="dmap">
      <div className="dmap__tools">
        <div className="seg">
          {[1, 2, 3].map((z) => (
            <button key={z} aria-pressed={zoom === z} onClick={() => setZoom(z)} disabled={z > 1 && !sel}>
              {z === 1 ? "Whole area" : `Zoom ${z}×`}
            </button>
          ))}
        </div>
        {!sel && <span className="muted">Select a driver to follow and zoom</span>}
      </div>
      <svg
        viewBox={`${focus[0] - e} ${focus[1] - e} ${2 * e} ${2 * e}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ height, width: "100%" }}
        role="img"
        aria-label="Live driver positions on a fictional delivery-area road map"
        data-testid="driver-map"
      >
        <rect x={-30} y={-30} width={60} height={60} className="dmap__bg" />
        {c?.parks.map((pk, i) => <circle key={i} cx={pk.x} cy={-pk.y} r={pk.r} className="dmap__park" />)}
        {c && <polyline points={pts(c.river)} className="dmap__river" />}
        {map.incidents.map((inc, i) => {
          const r = inc.target ? SECTOR_RECT[inc.target] : null;
          return r ? <rect key={i} x={r[0]} y={r[1]} width={r[2]} height={r[3]} className="dmap__incident" /> : null;
        })}
        {c?.roads
          .filter((r) => r.kind === "street")
          .map((r, i) => (
            <polyline key={`s${i}`} points={pts(r.points)} className={`dmap__road dmap__road--street${r.bridge ? " dmap__road--bridge" : ""}`} />
          ))}
        {c?.roads
          .filter((r) => r.kind !== "street")
          .map((r, i) => (
            <polyline key={`h${i}`} points={pts(r.points)} className={`dmap__road dmap__road--${r.kind}`} />
          ))}
        {c?.bridges.map((b, i) => <rect key={i} x={b[0] - 0.25} y={-b[1] - 0.25} width={0.5} height={0.5} className="dmap__bridge" />)}
        {map.zones.map((z) => (
          <circle key={z.route_id} cx={z.x} cy={-z.y} r={1.4} className="dmap__zone" />
        ))}
        {c?.neighbourhoods.map((n) => (
          <text key={n.name} x={n.x} y={-n.y} className="dmap__hood" textAnchor="middle">
            {n.name}
          </text>
        ))}
        {p && (
          <g className="dmap__path">
            {(sel?.state === "en_route" || sel?.state === "off_duty") && <polyline points={pts(p.to_station)} className="dmap__route dmap__route--in" />}
            {sel?.state !== "en_route" && sel?.state !== "off_duty" && (
              <>
                <polyline points={pts(p.out)} className="dmap__route" />
                <polyline points={pts(p.tour)} className="dmap__route dmap__route--tour" />
                <polyline points={pts(p.back)} className="dmap__route dmap__route--back" />
                {p.tour.map(([x, y], i) => (
                  <circle key={i} cx={x} cy={-y} r={0.28} className={i < p.stops_done_display ? "dmap__stop dmap__stop--done" : "dmap__stop"} />
                ))}
              </>
            )}
          </g>
        )}
        <rect x={-2.1} y={0.6} width={4.2} height={3.4} rx={0.3} className="dmap__yard" />
        <rect x={-1.2} y={-1.2} width={2.4} height={2.4} rx={0.4} className="dmap__station" />
        <text x={0} y={-1.7} className="dmap__label" textAnchor="middle">
          Station
        </text>
        {drivers.map((d) => {
          const late = (d.late_by ?? 0) > 0 && (d.state === "off_duty" || d.state === "en_route");
          const flagged = late || d.no_show_suspected || d.state === "grounded";
          const r = (selected === d.driver_id ? 0.95 : 0.55) / Math.sqrt(zoom);
          return (
            <g key={d.driver_id} onClick={() => onSelect?.(d)} className="dmap__driver">
              <circle
                cx={d.x}
                cy={-d.y}
                r={r}
                style={{ fill: STATE_COLOR[d.state] ?? "var(--text-muted)" }}
                className={flagged ? "dmap__dot dmap__dot--late" : "dmap__dot"}
              >
                <title>
                  {`${d.driver_id} · ${d.dsp} · ${d.route_id} · ${STATE_LABEL[d.state] ?? d.state.replace(/_/g, " ")}`}
                  {d.late_by ? ` · ${d.late_by.toFixed(0)} min late` : ""}
                  {d.state === "on_road" ? ` · stop ${d.stops_done}/${d.stops_total}` : ""}
                  {d.vsa_defect ? ` · VSA: ${d.vsa_defect}` : ""}
                </title>
              </circle>
            </g>
          );
        })}
      </svg>
      <div className="dmap__legend">
        {Object.entries(STATE_LABEL).map(([k, v]) => (
          <span key={k}>
            <i style={{ background: STATE_COLOR[k] }} />
            {v}
          </span>
        ))}
        <span>
          <i className="dmap__legend-late" />
          Late / no-show / grounded
        </span>
        <span>
          <i className="dmap__legend-incident" />
          Traffic incident sector
        </span>
        <span className="muted">Fictional area · highways, ring roads, river with bridges</span>
      </div>
    </div>
  );
}
