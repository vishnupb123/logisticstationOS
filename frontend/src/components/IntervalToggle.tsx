// One interval toggle for every interval grid (HANDOFF_V2 §11.4): 15 min /
// 30 min / 1 hour / Cumulative. The value is the number of 15-minute
// intervals per column; 0 means one cumulative column.
export type IntervalSize = 1 | 2 | 4 | 0;

const INTERVALS: { n: IntervalSize; label: string }[] = [
  { n: 1, label: "15 min" },
  { n: 2, label: "30 min" },
  { n: 4, label: "1 hour" },
  { n: 0, label: "Cumulative" },
];

export function IntervalToggle({
  value,
  onChange,
  label = "Interval",
}: {
  value: IntervalSize;
  onChange: (n: IntervalSize) => void;
  label?: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label} data-testid="interval-toggle">
      {INTERVALS.map((i) => (
        <button key={i.n} type="button" aria-pressed={value === i.n} onClick={() => onChange(i.n)}>
          {i.label}
        </button>
      ))}
    </div>
  );
}
