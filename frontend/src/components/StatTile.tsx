// A hero number, not a chart — per the dataviz skill's own form
// heuristic: a single magnitude with no comparison/trend to show is a
// stat tile, not a chart forced to carry one data point.
import "./StatTile.css";

export function StatTile({
  label,
  value,
  caption,
}: {
  label: string;
  value: string | number;
  caption?: string;
}) {
  return (
    <div className="stat-tile">
      <div className="stat-tile__label">{label}</div>
      <div className="stat-tile__value">{value}</div>
      {caption && <div className="stat-tile__caption">{caption}</div>}
    </div>
  );
}
