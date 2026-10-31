// A single-series time line — no legend needed (the card title names
// the series), a thin line per the dataviz skill's mark specs. Axis
// labels are plain HTML below the SVG, not SVG <text> — see
// GroupedBarChart.tsx's comment for why (preserveAspectRatio="none"
// distorts text glyphs, found by actually looking at a screenshot).
import { useState } from "react";
import "./charts.css";

export interface LinePoint {
  label: string;
  value: number;
}

export function LineChart({
  points,
  color = "var(--series-1)",
  height = 200,
  valueFormatter = (v: number) => v.toLocaleString(),
}: {
  points: LinePoint[];
  color?: string;
  height?: number;
  valueFormatter?: (value: number) => string;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (points.length === 0) {
    return <div className="chart-empty">No data to show.</div>;
  }

  const maxValue = Math.max(1, ...points.map((p) => p.value));
  const stepX = points.length > 1 ? 100 / (points.length - 1) : 0;

  const coords = points.map((p, i) => ({
    x: points.length > 1 ? i * stepX : 50,
    y: height - (p.value / maxValue) * height,
  }));

  const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x},${c.y}`).join(" ");
  const labelEvery = Math.max(1, Math.floor(points.length / 6));

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        className="chart-svg"
        style={{ height }}
      >
        <line x1={0} x2={100} y1={height} y2={height} className="chart-baseline" />
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth={0.6}
          vectorEffect="non-scaling-stroke"
        />
        {coords.map((c, i) => (
          <circle
            key={points[i].label + i}
            cx={c.x}
            cy={c.y}
            r={hoverIndex === i ? 1.6 : 1}
            fill={color}
            onMouseEnter={() => setHoverIndex(i)}
            onMouseLeave={() => setHoverIndex(null)}
          >
            <title>
              {points[i].label}: {valueFormatter(points[i].value)}
            </title>
          </circle>
        ))}
      </svg>
      <div className="chart-axis-labels">
        {points.map((p, i) => (
          <span key={p.label + i} style={{ flex: 1 }}>
            {i % labelEvery === 0 ? p.label : ""}
          </span>
        ))}
      </div>
      {hoverIndex !== null && (
        <div className="chart-tooltip">
          <strong>{points[hoverIndex].label}</strong>: {valueFormatter(points[hoverIndex].value)}
        </div>
      )}
    </div>
  );
}
