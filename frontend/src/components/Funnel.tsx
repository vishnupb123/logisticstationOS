// End-to-end stage funnel: one horizontal bar per stage on a single
// shared scale (one axis), magnitude in one hue, with each stage's
// count and its conversion from the previous stage as text labels.
import "./Funnel.css";

export interface FunnelStage {
  key: string;
  label: string;
  value: number;
  note?: string;
}

export function Funnel({ stages, total }: { stages: FunnelStage[]; total?: number }) {
  const max = Math.max(1, total ?? 0, ...stages.map((s) => s.value));
  return (
    <div className="funnel" role="table" aria-label="End-to-end stage funnel">
      {stages.map((stage, i) => {
        const prev = i > 0 ? stages[i - 1].value : null;
        const conversion = prev ? (stage.value / prev) * 100 : null;
        return (
          <div className="funnel__row" role="row" key={stage.key} data-testid={`funnel-${stage.key}`}>
            <div className="funnel__label" role="cell">
              {stage.label}
              {stage.note && <span className="funnel__note">{stage.note}</span>}
            </div>
            <div className="funnel__track" role="cell">
              <div className="funnel__bar" style={{ width: `${(stage.value / max) * 100}%` }} />
            </div>
            <div className="funnel__value" role="cell">
              {stage.value.toLocaleString()}
            </div>
            <div className="funnel__conv" role="cell">
              {conversion !== null ? `${conversion.toFixed(0)}%` : ""}
            </div>
          </div>
        );
      })}
    </div>
  );
}
