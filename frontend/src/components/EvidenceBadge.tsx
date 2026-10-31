// Fixed categorical color per evidence category (docs/AGENTIC_ARCHITECTURE.md
// §"Evidence provenance") — a memorable, consistent color, never the
// only way to tell categories apart (the text label IS the name of
// the category, so identity never depends on color alone).
import type { EvidenceCategory } from "../api/types";
import "./EvidenceBadge.css";

const SLOT: Record<EvidenceCategory, number> = {
  observation: 1,
  calculated: 3,
  inferred: 7,
  hypothesis: 4,
  prediction: 5,
  recommendation: 2,
};

export function EvidenceBadge({ category }: { category: EvidenceCategory }) {
  return (
    <span
      className="evidence-badge"
      style={{ "--slot": `var(--series-${SLOT[category]})` } as React.CSSProperties}
    >
      {category}
    </span>
  );
}
