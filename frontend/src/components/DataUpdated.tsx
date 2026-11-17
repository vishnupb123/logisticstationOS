// "Data last updated HH:MM (simulated)" under every live table (HANDOFF_V2 §11.2).
// The time is the simulated session clock, never wall-clock time.
import "./StatusTree.css";

export function DataUpdated({ clock }: { clock: string | null | undefined }) {
  return (
    <p className="data-updated" data-testid="data-updated">
      Data last updated <span className="tabular">{clock ?? "—"}</span> (simulated)
    </p>
  );
}
