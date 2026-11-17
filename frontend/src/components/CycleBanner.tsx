// Global cycle banner (HANDOFF_V2 E2/§11): shows cycle state only — e.g. pick
// has started, so induct into the cycle is blocked — with the actionable
// levers. Every lever acts on the simulated twin only and is logged.
import { useState } from "react";
import { useStation, useStationAction } from "../api/runtime";
import "./CycleBanner.css";

export function CycleBanner() {
  const q = useStation();
  const act = useStationAction();
  const [effect, setEffect] = useState<string | null>(null);
  const c = q.data?.views.cycles;
  if (!c?.banner) return null;
  const forcing = c.cycles.some((x) => x.force_induct);
  const run = (kind: string, amount?: number) =>
    act.mutate(
      { kind, ...(amount !== undefined ? { amount } : {}) },
      { onSuccess: (r) => setEffect(`${r.clock} · ${r.effect}`), onError: (e) => setEffect(String(e.message)) },
    );
  return (
    <div className="cbanner" role="status" data-testid="cycle-banner">
      <div className="cbanner__msg">
        <span className="cbanner__tag">
          <span aria-hidden>⚠</span> Cycle
        </span>
        <span>{c.banner}</span>
      </div>
      <div className="cbanner__counts tabular">
        <span data-testid="cycle-missed">
          <strong>{c.on_floor_missed_cycle.toLocaleString()}</strong> on floor, missed cycle
        </span>
        <span>
          <strong>{c.next_cycle.toLocaleString()}</strong> moved to next cycle
        </span>
        <span>
          <strong>{c.held_wrong_cycle.toLocaleString()}</strong> held, wrong cycle
        </span>
        {forcing && <span className="cbanner__forcing">Force induct active</span>}
      </div>
      <div className="cbanner__actions">
        <button className="button button--sm" disabled={act.isPending} onClick={() => run("force_induct", 15)} data-testid="cycle-force-induct">
          Force induct 15 min
        </button>
        <button className="button button--sm" disabled={act.isPending} onClick={() => run("change_cycle")} data-testid="cycle-change">
          Change cycle
        </button>
        <button className="button button--sm" disabled={act.isPending} onClick={() => run("enable_cycle", 4)} data-testid="cycle-enable">
          Enable next cycle 4h
        </button>
        {effect && (
          <span className="cbanner__effect" role="status" data-testid="cycle-effect">
            {effect}
          </span>
        )}
      </div>
    </div>
  );
}
