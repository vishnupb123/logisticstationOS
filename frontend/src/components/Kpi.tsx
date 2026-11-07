// KPI tile: a hero number with unit, caption, and an optional status
// (status colors are reserved for state and always paired with a text
// label — never color alone, per the dataviz skill).
import type { ReactNode } from "react";
import "./Kpi.css";

export type KpiStatus = "good" | "warning" | "critical";

const STATUS_LABEL: Record<KpiStatus, string> = {
  good: "On track",
  warning: "Watch",
  critical: "Action",
};

export function Kpi({
  label,
  value,
  unit,
  caption,
  status,
  testId,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  caption?: ReactNode;
  status?: KpiStatus;
  testId?: string;
}) {
  return (
    <div className="kpi" data-testid={testId}>
      <div className="kpi__top">
        <span className="kpi__label">{label}</span>
        {status && (
          <span className={`kpi__status kpi__status--${status}`}>
            <span className="kpi__dot" aria-hidden />
            {STATUS_LABEL[status]}
          </span>
        )}
      </div>
      <div className="kpi__value">
        {value}
        {unit && <span className="kpi__unit">{unit}</span>}
      </div>
      {caption && <div className="kpi__caption">{caption}</div>}
    </div>
  );
}

export function KpiGrid({ children }: { children: ReactNode }) {
  return <div className="kpi-grid">{children}</div>;
}
