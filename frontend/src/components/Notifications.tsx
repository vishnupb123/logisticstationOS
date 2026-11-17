// Notification centre: what the (simulated) station would push to the
// supervisor, the manager, and DSPs/drivers — wrong staging scans, bags left
// in aisles, grounded vans, replacement vans, truckfile revisions after the
// final, call-outs, GTDRs. Acknowledge one or all. Nobody real is contacted.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { type Notification, runtimeApi, useStation } from "../api/runtime";
import "./Notifications.css";

const AUDIENCES = ["supervisor", "manager", "dsp", "all"] as const;
type Aud = (typeof AUDIENCES)[number];

function useAck() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => runtimeApi.ack(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live-state"] }),
  });
}

export function NotificationList({ items, audience, compact }: { items: Notification[]; audience: Aud; compact?: boolean }) {
  const ack = useAck();
  const shown = items.filter((n) => audience === "all" || n.audience === audience).slice(0, compact ? 40 : 200);
  if (!shown.length) return <p className="muted ntf__empty">Nothing here.</p>;
  return (
    <ul className="ntf__list" data-testid="notification-list">
      {shown.map((n) => (
        <li key={n.id} className={`ntf__item ntf__item--${n.severity}${n.ack ? " ntf__item--ack" : ""}`}>
          <div className="ntf__head">
            <span className={`ntf__sev ntf__sev--${n.severity}`} aria-label={n.severity}>
              {n.severity === "critical" ? "!" : n.severity === "warning" ? "▲" : "i"}
            </span>
            <strong>{n.title}</strong>
            <span className="ntf__meta tabular">
              {n.clock} · {n.audience}
            </span>
          </div>
          <div className="ntf__msg">{n.message}</div>
          {!n.ack ? (
            <button className="button button--sm" onClick={() => ack.mutate(n.id)} data-testid={`ack-${n.id}`}>
              Acknowledge
            </button>
          ) : (
            <span className="ntf__acked">✓ acknowledged {n.acked_at}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export function NotificationBell() {
  const q = useStation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [aud, setAud] = useState<Aud>("supervisor");
  const ref = useRef<HTMLDivElement>(null);
  const ackAll = useMutation({
    mutationFn: () => runtimeApi.ackAll(aud),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["live-state"] }),
  });
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const n = q.data?.views.notifications;
  const unacked = n ? (n.unacked.supervisor ?? 0) + (n.unacked.manager ?? 0) : 0;
  const wi = q.data?.views.work_items_v2?.summary;
  const pending = wi?.pending ?? 0;
  const badge = unacked + pending;
  return (
    <div className="ntf" ref={ref}>
      <button
        className={`ntf__bell${n?.critical_unacked ? " ntf__bell--hot" : ""}`}
        aria-label={`Inbox: ${pending} pending work items, ${unacked} unacknowledged notifications`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        data-testid="notification-bell"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
          <path d="M6 17V11a6 6 0 0 1 12 0v6l2 2H4zM10 21h4" />
        </svg>
        {badge > 0 && <span className="ntf__count">{badge > 99 ? "99+" : badge}</span>}
      </button>
      {open && n && (
        <div className="ntf__panel" role="dialog" aria-label="Notifications">
          <div className="ntf__wi" data-testid="bell-work-items">
            <span>
              <strong className="tabular">{pending}</strong> pending work item{pending === 1 ? "" : "s"}
              {wi?.high_priority ? <> · <strong className="tabular">{wi.high_priority}</strong> high priority</> : null}
            </span>
            <Link to="/work-items" className="button button--sm" onClick={() => setOpen(false)}>
              Open work items →
            </Link>
          </div>
          <div className="ntf__bar">
            <div className="seg">
              {AUDIENCES.map((a) => (
                <button key={a} aria-pressed={aud === a} onClick={() => setAud(a)}>
                  {a === "dsp" ? "DSP / drivers" : a}
                  {a !== "all" && (n.unacked[a] ?? 0) > 0 ? ` (${n.unacked[a]})` : ""}
                </button>
              ))}
            </div>
            <button className="button button--sm" onClick={() => ackAll.mutate()} disabled={ackAll.isPending}>
              Acknowledge all
            </button>
          </div>
          <NotificationList items={n.items} audience={aud} compact />
        </div>
      )}
    </div>
  );
}
