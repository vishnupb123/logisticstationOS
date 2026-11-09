// Live driver map of a *fictional* delivery area: a km grid around the
// station, route zones, sector traffic incidents, and every driver's
// simulated position (en route to the station, at the station, or out on
// their route). No real geography — the twin's map is synthetic.
// Uniform scaling (viewBox + xMidYMid meet), so <text> labels don't distort.
import type { DriverRow, Views } from "../api/runtime";
import "./DriverMap.css";

const STATE_COLOR: Record<string, string> = {
  off_duty: "var(--text-muted)",
  en_route: "var(--series-1)",
  checked_in: "var(--series-7)",
  loading: "var(--series-7)",
  on_road: "var(--series-3)",
  pending_swipe: "var(--series-4)",
  finished: "var(--series-6)",
};
const SECTOR_RECT: Record<string, [number, number, number, number]> = {
  N: [-26, -26, 52, 18],
  S: [-26, 8, 52, 18],
  W: [-26, -26, 18, 52],
  E: [8, -26, 18, 52],
};
const STATE_LABEL: Record<string, string> = {
  off_duty: "Not yet left",
  en_route: "En route to station",
  checked_in: "At station",
  on_road: "On road",
  pending_swipe: "Returned, not swiped",
  finished: "Finished",
};

export function DriverMap({
  map,
  drivers,
  selected,
  onSelect,
  height = 460,
}: {
  map: Views["dispatch"]["map"];
  drivers: DriverRow[];
  selected?: string | null;
  onSelect?: (d: DriverRow) => void;
  height?: number;
}) {
  const e = map.extent_km;
  const grid = [-20, -10, 0, 10, 20];
  return (
    <div className="dmap">
      <svg
        viewBox={`${-e} ${-e} ${2 * e} ${2 * e}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ height, width: "100%" }}
        role="img"
        aria-label="Live driver positions on a fictional delivery-area map"
        data-testid="driver-map"
      >
        <rect x={-e} y={-e} width={2 * e} height={2 * e} className="dmap__bg" />
        {map.incidents.map((inc, i) => {
          const r = inc.target ? SECTOR_RECT[inc.target] : null;
          return r ? <rect key={i} x={r[0]} y={r[1]} width={r[2]} height={r[3]} className="dmap__incident" /> : null;
        })}
        {grid.map((g) => (
          <g key={g}>
            <line x1={g} x2={g} y1={-e} y2={e} className="dmap__grid" />
            <line y1={g} y2={g} x1={-e} x2={e} className="dmap__grid" />
          </g>
        ))}
        {[5, 10, 15].map((r) => (
          <circle key={r} cx={0} cy={0} r={r} className="dmap__ring" />
        ))}
        {map.zones.map((z) => (
          <circle key={z.route_id} cx={z.x} cy={-z.y} r={1.6} className="dmap__zone" />
        ))}
        <rect x={-1.2} y={-1.2} width={2.4} height={2.4} rx={0.4} className="dmap__station" />
        <text x={0} y={-2} className="dmap__label" textAnchor="middle">
          Station
        </text>
        {(["N", "S", "E", "W"] as const).map((s) => {
          const pos = { N: [0, -e + 2], S: [0, e - 1], E: [e - 2, 0.6], W: [-e + 2, 0.6] }[s];
          return (
            <text key={s} x={pos[0]} y={pos[1]} className="dmap__sector" textAnchor="middle">
              {s}
            </text>
          );
        })}
        {drivers.map((d) => {
          const late = (d.late_by ?? 0) > 0 && (d.state === "off_duty" || d.state === "en_route");
          return (
            <g key={d.driver_id} onClick={() => onSelect?.(d)} className="dmap__driver">
              <circle
                cx={d.x}
                cy={-d.y}
                r={selected === d.driver_id ? 1.1 : 0.65}
                style={{ fill: STATE_COLOR[d.state] ?? "var(--text-muted)" }}
                className={late || d.no_show_suspected ? "dmap__dot dmap__dot--late" : "dmap__dot"}
              >
                <title>
                  {`${d.driver_id} · ${d.dsp} · ${d.route_id} · ${STATE_LABEL[d.state] ?? d.state}`}
                  {d.late_by ? ` · ${d.late_by.toFixed(0)} min late` : ""}
                  {d.state === "on_road" ? ` · stop ${d.stops_done}/${d.stops_total}` : ""}
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
          Late / suspected no-show
        </span>
        <span>
          <i className="dmap__legend-incident" />
          Traffic incident sector
        </span>
        <span className="muted">Grid = 10 km · fictional area</span>
      </div>
    </div>
  );
}
