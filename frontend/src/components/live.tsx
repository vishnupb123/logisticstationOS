// Shared live-page helpers: the gate every live page renders through, an
// action button that applies a lever to the simulated station and shows the
// honest effect, simple tabs, and a status pill.
import { type ReactNode, useState } from "react";
import { type LiveState, type StationAction, useStation, useStationAction } from "../api/runtime";
import { ErrorState, LoadingState } from "./QueryStates";
import "./live.css";

export function LiveGate({ children }: { children: (s: LiveState) => ReactNode }) {
  const q = useStation();
  if (q.isLoading) return <LoadingState />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data) return null;
  return <>{children(q.data)}</>;
}

export function ActButton({
  action,
  label,
  variant = "default",
  testId,
  confirm,
}: {
  action: StationAction;
  label: string;
  variant?: "default" | "primary" | "danger";
  testId?: string;
  confirm?: string;
}) {
  const m = useStationAction();
  const [effect, setEffect] = useState<string | null>(null);
  return (
    <span className="act">
      <button
        className={`button button--sm${variant === "default" ? "" : ` button--${variant}`}`}
        disabled={m.isPending}
        data-testid={testId}
        onClick={() => {
          if (confirm && !window.confirm(confirm)) return;
          m.mutate(action, { onSuccess: (r) => setEffect(r.effect) });
        }}
      >
        {m.isPending ? "…" : label}
      </button>
      {effect && (
        <span className={`act__effect${effect.startsWith("no-op") ? " act__effect--noop" : ""}`} role="status">
          {effect}
        </span>
      )}
      {m.error && <span className="act__effect act__effect--noop">{String(m.error.message)}</span>}
    </span>
  );
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: readonly T[] | { key: T; label: ReactNode }[];
  value: T;
  onChange: (t: T) => void;
}) {
  const items = (tabs as (T | { key: T; label: ReactNode })[]).map((t) =>
    typeof t === "string" ? { key: t as T, label: t as ReactNode } : t,
  );
  return (
    <div className="cc-tabs" role="tablist">
      {items.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={value === t.key}
          className={"cc-tab" + (value === t.key ? " cc-tab--active" : "")}
          onClick={() => onChange(t.key)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

const TONE: Record<string, string> = {
  departed: "good",
  staged: "good",
  arrived: "good",
  finished: "good",
  on_road: "info",
  loading: "info",
  checked_in: "info",
  picking: "info",
  unloading: "info",
  running: "good",
  online: "good",
  staging: "warn",
  ready: "warn",
  in_yard: "warn",
  en_route: "info",
  pending_swipe: "warn",
  degraded: "warn",
  low_battery: "warn",
  jam: "bad",
  planned: "warn",
  down: "bad",
  cancelled: "bad",
  no_show: "bad",
};

export function Pill({ value, label }: { value: string; label?: string }) {
  return <span className={`pill pill--${TONE[value] ?? "neutral"}`}>{label ?? value.replace(/_/g, " ")}</span>;
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mini-stat">
      <div className="mini-stat__label">{label}</div>
      <div className="mini-stat__value tabular">{value}</div>
      {sub && <div className="mini-stat__sub">{sub}</div>}
    </div>
  );
}

export function StatRow({ children }: { children: ReactNode }) {
  return <div className="mini-stats">{children}</div>;
}
