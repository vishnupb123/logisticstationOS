// Per-aisle hamper fill as a heat grid — sequential (one hue,
// light -> dark) because fill level is magnitude; the level/capacity
// number is printed in every cell so it's never color-alone.
import "./HamperGrid.css";

export function HamperGrid({
  hampers,
}: {
  hampers: { aisle_code: string; level: number; capacity: number }[];
}) {
  return (
    <div className="hamper-grid">
      {hampers.map((h) => {
        const ratio = h.capacity > 0 ? h.level / h.capacity : 0;
        const full = h.level >= h.capacity && h.capacity > 0;
        return (
          <div
            key={h.aisle_code}
            className={"hamper" + (full ? " hamper--full" : "")}
            style={{
              background: `color-mix(in srgb, var(--sequential-700) ${Math.round(ratio * 85)}%, var(--sequential-100))`,
              color: ratio > 0.5 ? "var(--on-fill)" : "var(--text-primary)",
            }}
            title={`${h.aisle_code}: ${h.level}/${h.capacity}${full ? " — full, new sorts jackpot" : ""}`}
          >
            <span className="hamper__code">{h.aisle_code}</span>
            <span className="hamper__level">
              {h.level}/{h.capacity}
            </span>
          </div>
        );
      })}
    </div>
  );
}
