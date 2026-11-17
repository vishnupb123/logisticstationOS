// "How this is calculated" (HANDOFF_V2 E1/E11): an ⓘ button next to any
// metric that opens a small drawer with the metric's label, provenance
// (documented / observed / proposed — always as text, never colour alone),
// the formula, and the current inputs the metric engine used. Reads the one
// shared simulated session itself, so it can be dropped next to any number.
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useStation } from "../api/runtime";
import type { Provenance } from "../api/runtimeV2";
import "./MetricDrawer.css";

const PROVENANCE_TEXT: Record<Provenance, string> = {
  documented: "Defined by the station owner (formula documented).",
  observed: "Seen on station screens; exact semantics still to confirm.",
  proposed: "Proposed by StationOS — an assumption, not a validated definition.",
};

export function ProvenanceBadge({ status }: { status: string }) {
  const known = status === "documented" || status === "observed" || status === "proposed";
  const icon = status === "documented" ? "✓" : status === "observed" ? "◐" : "?";
  return (
    <span
      className={`prov prov--${known ? status : "proposed"}`}
      title={known ? PROVENANCE_TEXT[status as Provenance] : status}
      data-testid="provenance-badge"
    >
      <span aria-hidden>{icon}</span> {status}
    </span>
  );
}

function fmtNum(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return String(v);
  return v.toLocaleString(undefined, { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : digits });
}

const label = (k: string) => k.replace(/_/g, " ");

/** One input value, rendered compactly: numbers formatted, pairs and objects inline. */
function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return fmtNum(v);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    if (v.length === 0) return "none";
    // [[name, value], …] → "AUTO-1 0.75 · L2 0.33"
    if (v.every((x) => Array.isArray(x) && x.length === 2)) {
      return v.map((x) => `${fmtValue(x[0])} ${fmtValue(x[1])}`).join(" · ");
    }
    if (v.every((x) => typeof x !== "object" || x === null)) return v.map(fmtValue).join(" – ");
    // a long list of records (e.g. an interval timeline): count + the latest
    const last = v[v.length - 1];
    return `${v.length} entries · latest ${fmtValue(last)}`;
  }
  if (typeof v === "object") {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, x]) => `${label(k)} ${fmtValue(x)}`)
      .join(" · ");
  }
  return String(v);
}

/** For a few documented metrics, show the arithmetic with the current inputs. */
function worked(key: string, inputs: Record<string, unknown>, value: number | null): string | null {
  const n = (k: string) => (typeof inputs[k] === "number" ? (inputs[k] as number) : null);
  if (key === "stow_wip_minutes" && n("inc_pending_stow") !== null && n("stow_fph") !== null) {
    if (!n("stow_fph")) return `INC ${fmtNum(n("inc_pending_stow")!)} ÷ Stow FPH 0 → no stow flow`;
    return `INC ${fmtNum(n("inc_pending_stow")!)} ÷ Stow FPH ${fmtNum(n("stow_fph")!)} × 60 = ${value === null ? "—" : fmtNum(value, 1)} min`;
  }
  if (key === "stow_wip_compliance" && n("intervals")) {
    return `${fmtNum(n("within")!)} of ${fmtNum(n("intervals")!)} intervals in band = ${value === null ? "—" : `${(value * 100).toFixed(1)}%`}`;
  }
  if (key === "induct_downtime_dpmo" && n("inducted")) {
    return `${fmtNum(n("stops")!)} stops ÷ ${fmtNum(n("inducted")!)} inducted × 1,000,000 = ${value === null ? "—" : fmtNum(value)}`;
  }
  if (key === "induct_fph" && n("inducted_in_window") !== null && n("window_minutes")) {
    return `${fmtNum(n("inducted_in_window")!)} in last ${n("window_minutes")} min × ${fmtNum(60 / n("window_minutes")!)} = ${value === null ? "—" : fmtNum(value)}/h`;
  }
  return null;
}

/** "Data last updated <sim clock>" line shown under live tables (§11). */
export function DataUpdated() {
  const q = useStation();
  const clock = q.data?.snapshot.clock;
  if (!clock) return null;
  return (
    <div className="data-updated tabular" data-testid="data-updated">
      Data last updated {clock} (simulated clock)
    </div>
  );
}

function fmtMetric(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined) return "—";
  if (unit === "ratio") return `${(v * 100).toFixed(1)}%`;
  if (unit === "minutes") return `${fmtNum(v, 1)} min`;
  if (unit === "hours") return `${fmtNum(v)} h`;
  if (unit === "per_hour") return `${fmtNum(v)}/h`;
  return fmtNum(v);
}

export function MetricInfo({ metricKey, labelOverride }: { metricKey: string; labelOverride?: string }) {
  const q = useStation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const spec = q.data?.views.metric_specs?.[metricKey];
  const metric = q.data?.snapshot.metrics[metricKey];
  const name = labelOverride ?? spec?.label ?? label(metricKey);
  const inputs = (metric?.inputs ?? {}) as Record<string, unknown>;
  const entries = Object.entries(inputs);
  const unit = spec?.unit ?? metric?.unit ?? "";
  const calc = metric ? worked(metricKey, inputs, metric.value) : null;

  return (
    <span className="minfo" ref={ref}>
      <button
        type="button"
        className="minfo__btn"
        aria-label={`How ${name} is calculated`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((o) => !o)}
        data-testid={`metric-info-${metricKey}`}
      >
        ⓘ
      </button>
      {open && (
        <div className="minfo__panel" role="dialog" aria-label={`How ${name} is calculated`} id={id} data-testid="metric-drawer">
          <div className="minfo__head">
            <div>
              <div className="minfo__eyebrow">How this is calculated</div>
              <strong className="minfo__title">{name}</strong>
            </div>
            <button type="button" className="minfo__close" aria-label="Close" onClick={() => setOpen(false)}>
              ×
            </button>
          </div>
          {spec ? (
            <>
              <ProvenanceBadge status={spec.status} />
              <p className="minfo__formula">{spec.formula}</p>
            </>
          ) : (
            <p className="minfo__formula muted">No formula registered for this metric yet — treat it as proposed.</p>
          )}
          {metric && (
            <dl className="minfo__kv">
              <dt>Current value</dt>
              <dd className="tabular">{fmtMetric(metric.value, unit)}</dd>
              {metric.target !== null && metric.target !== undefined && (
                <>
                  <dt>{metric.target_max != null ? "Target band" : "Target"}</dt>
                  <dd className="tabular">
                    {fmtMetric(metric.target, unit)}
                    {metric.target_max != null ? ` – ${fmtMetric(metric.target_max, unit)}` : ""}
                  </dd>
                </>
              )}
            </dl>
          )}
          {calc && <p className="minfo__calc tabular" data-testid="metric-calc">{calc}</p>}
          <div className="minfo__sub">Current inputs</div>
          {entries.length === 0 ? (
            <p className="muted minfo__empty">No inputs yet — they appear once the shift produces data.</p>
          ) : (
            <dl className="minfo__kv">
              {entries.map(([k, v]) => (
                <div key={k} className="minfo__row">
                  <dt>{label(k)}</dt>
                  <dd className="tabular">{fmtValue(v)}</dd>
                </div>
              ))}
            </dl>
          )}
          <div className="minfo__foot">
            Simulated run · <Link to="/settings" onClick={() => setOpen(false)}>Thresholds in Settings →</Link>
          </div>
        </div>
      )}
    </span>
  );
}
