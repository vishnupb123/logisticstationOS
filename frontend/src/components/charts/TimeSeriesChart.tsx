// A multi-series time-series line chart rendered in true pixel
// coordinates (width measured with a ResizeObserver) — unlike the
// older viewBox-stretched charts, nothing is distorted, so SVG <text>
// axis ticks are safe here (see frontend/README.md's SVG gotchas: both
// stemmed from preserveAspectRatio="none", which this chart doesn't
// use). Follows the dataviz skill: one y-axis only, 2px lines, fixed
// categorical slot per series, legend for >= 2 series plus direct end
// labels for <= 4, recessive grid, crosshair + tooltip on hover.
import { useLayoutEffect, useRef, useState } from "react";
import "./charts.css";

export interface TimeSeries {
  key: string;
  label: string;
  color: string; // a `var(--series-N)` token — fixed per entity, never per rank
  values: number[]; // aligned with `x`
}

const PAD = { top: 12, right: 64, bottom: 26, left: 44 };

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(value)));
  const f = value / exp;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10;
  return nice * exp;
}

export function TimeSeriesChart({
  x,
  series,
  height = 220,
  xFormatter = (v: number) => String(v),
  valueFormatter = (v: number) => v.toLocaleString(),
  yMax,
  ariaLabel,
}: {
  x: number[];
  series: TimeSeries[];
  height?: number;
  xFormatter?: (v: number) => string;
  valueFormatter?: (v: number) => string;
  yMax?: number;
  ariaLabel: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState<number | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = Math.floor(entries[0].contentRect.width);
      if (w > 0) setWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (x.length === 0) {
    return (
      <div ref={ref} className="chart-empty">
        Waiting for data…
      </div>
    );
  }

  const innerW = Math.max(10, width - PAD.left - PAD.right);
  const innerH = height - PAD.top - PAD.bottom;
  const xMin = x[0];
  const xMax = Math.max(x[x.length - 1], xMin + 1);
  const dataMax = Math.max(0, ...series.flatMap((s) => s.values));
  const top = yMax ?? niceMax(dataMax);
  const sx = (v: number) => PAD.left + ((v - xMin) / (xMax - xMin)) * innerW;
  const sy = (v: number) => PAD.top + innerH - (Math.min(v, top) / top) * innerH;
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  const xTicks = Array.from({ length: 5 }, (_, i) => xMin + ((xMax - xMin) * i) / 4);
  const last = x.length - 1;

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const target = xMin + (px / rect.width) * (xMax - xMin);
    let best = 0;
    for (let i = 1; i < x.length; i++) {
      if (Math.abs(x[i] - target) < Math.abs(x[best] - target)) best = i;
    }
    setHover(best);
  };

  return (
    <div className="chart" ref={ref}>
      {series.length >= 2 && (
        <div className="chart-legend">
          {series.map((s) => (
            <span key={s.key} className="chart-legend__item">
              <span className="chart-legend__swatch" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <svg width={width} height={height} role="img" aria-label={ariaLabel} className="ts-svg">
        {yTicks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={PAD.left + innerW}
              y1={sy(t)}
              y2={sy(t)}
              className={t === 0 ? "ts-baseline" : "ts-grid"}
            />
            <text x={PAD.left - 8} y={sy(t)} className="ts-tick" textAnchor="end" dy="0.32em">
              {valueFormatter(Math.round(t * 10) / 10)}
            </text>
          </g>
        ))}
        {xTicks.map((t, i) => (
          <text
            key={i}
            x={sx(t)}
            y={height - 6}
            className="ts-tick"
            textAnchor={i === 0 ? "start" : i === 4 ? "end" : "middle"}
          >
            {xFormatter(t)}
          </text>
        ))}
        {series.map((s) => {
          const d = s.values.map((v, i) => `${i === 0 ? "M" : "L"}${sx(x[i])},${sy(v)}`).join("");
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />
              {series.length <= 4 && (
                <text
                  x={sx(x[last]) + 6}
                  y={sy(s.values[last])}
                  dy="0.32em"
                  className="ts-direct-label"
                >
                  {valueFormatter(s.values[last])}
                </text>
              )}
            </g>
          );
        })}
        {hover !== null && (
          <g>
            <line
              x1={sx(x[hover])}
              x2={sx(x[hover])}
              y1={PAD.top}
              y2={PAD.top + innerH}
              className="ts-crosshair"
            />
            {series.map((s) => (
              <circle
                key={s.key}
                cx={sx(x[hover])}
                cy={sy(s.values[hover])}
                r={4}
                fill={s.color}
                stroke="var(--surface-1)"
                strokeWidth={2}
              />
            ))}
          </g>
        )}
        <rect
          x={PAD.left}
          y={PAD.top}
          width={innerW}
          height={innerH}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        />
      </svg>
      {hover !== null && (
        <div
          className="ts-tooltip"
          style={{
            left: Math.min(sx(x[hover]) + 10, width - 170),
            top: PAD.top,
          }}
        >
          <div className="ts-tooltip__title">{xFormatter(x[hover])}</div>
          {series.map((s) => (
            <div key={s.key} className="ts-tooltip__row">
              <span className="chart-legend__swatch" style={{ background: s.color }} />
              <span className="ts-tooltip__label">{s.label}</span>
              <strong>{valueFormatter(s.values[hover])}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
