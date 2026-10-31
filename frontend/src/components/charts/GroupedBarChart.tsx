// Inline SVG, no charting library — keeps the bundle light, and this
// app only needs two chart shapes. Follows the dataviz skill's mark
// specs: thin bars with rounded data-ends anchored to the baseline, a
// recessive gridline/baseline, a legend whenever there's more than one
// series (never for exactly one — the title/axis already names it),
// and a per-bar hover tooltip. Color is assigned by fixed categorical
// slot order, never generated/cycled per a filtered subset.
//
// Axis labels are plain HTML below the SVG, not SVG <text> — the SVG
// itself uses preserveAspectRatio="none" (independent X/Y scaling, so
// a viewBox like 100x220 fills a much wider-than-tall card correctly)
// and text glyphs inside that same transformed coordinate space render
// visibly distorted/illegible, since they get stretched by the same
// mismatched X/Y factors as the bars. Shapes tolerate that distortion
// fine; text doesn't — found by actually looking at a screenshot, not
// assumed.
import { useState } from "react";
import "./charts.css";

export interface BarSeries {
  key: string;
  label: string;
  color: string; // a `var(--series-N)` token
  values: number[]; // aligned with `categories`
}

export function GroupedBarChart({
  categories,
  series,
  height = 220,
  valueFormatter = (v: number) => v.toLocaleString(),
}: {
  categories: string[];
  series: BarSeries[];
  height?: number;
  valueFormatter?: (value: number) => string;
}) {
  const [hover, setHover] = useState<{ category: string; series: string; value: number } | null>(
    null,
  );

  if (categories.length === 0 || series.length === 0) {
    return <div className="chart-empty">No data to show.</div>;
  }

  const maxValue = Math.max(1, ...series.flatMap((s) => s.values));
  const groupWidth = 100 / categories.length;
  const barGap = 2; // % within a group, between series bars
  const barWidth = (groupWidth - barGap * (series.length + 1)) / series.length;

  return (
    <div className="chart">
      {series.length > 1 && (
        <div className="chart-legend">
          {series.map((s) => (
            <span key={s.key} className="chart-legend__item">
              <span className="chart-legend__swatch" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <svg
        viewBox={`0 0 100 ${height}`}
        preserveAspectRatio="none"
        className="chart-svg"
        style={{ height }}
      >
        <line x1={0} x2={100} y1={height} y2={height} className="chart-baseline" />
        {categories.map((category, ci) => {
          const groupX = ci * groupWidth;
          return (
            <g key={category}>
              {series.map((s, si) => {
                const value = s.values[ci] ?? 0;
                const barHeight = (value / maxValue) * height;
                const x = groupX + barGap + si * (barWidth + barGap);
                const y = height - barHeight;
                const isHovered = hover?.category === category && hover?.series === s.key;
                return (
                  <rect
                    key={s.key}
                    x={x}
                    y={y}
                    width={barWidth}
                    height={Math.max(barHeight, 1)}
                    rx={1.2}
                    fill={s.color}
                    opacity={isHovered ? 1 : 0.88}
                    onMouseEnter={() => setHover({ category, series: s.key, value })}
                    onMouseLeave={() => setHover(null)}
                  >
                    <title>
                      {s.label} · {category}: {valueFormatter(value)}
                    </title>
                  </rect>
                );
              })}
            </g>
          );
        })}
      </svg>
      <div className="chart-axis-labels">
        {categories.map((category) => (
          <span key={category} style={{ flexBasis: `${groupWidth}%` }}>
            {category}
          </span>
        ))}
      </div>
      {hover && (
        <div className="chart-tooltip">
          <strong>{hover.category}</strong> — {series.find((s) => s.key === hover.series)?.label}:{" "}
          {valueFormatter(hover.value)}
        </div>
      )}
    </div>
  );
}
