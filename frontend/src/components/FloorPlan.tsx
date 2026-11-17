// Live floor plans of the (simulated) station:
// - StagingFloor: every staging location by row/lane, colored by route state,
//   with wrong-scan carts, foreign carts, grounded vans, late stage and bags
//   left in aisles flagged in place; click a location for detail + actions.
// - AislePlan: the stow/pick aisles by cluster: bay fill, routes and their
//   pick state, who is in the aisle (pickers, sweeper), sweep status and
//   packages flagged as left behind.
import { useState } from "react";
import type { AisleCell, LiveState, StagingLoc } from "../api/runtime";
import { STATUS_LABEL } from "../api/runtime";
import { ActButton, Pill } from "./live";
import "./FloorPlan.css";

const SLOT: Record<string, number> = {
  not_ready: 8,
  ready: 4,
  picking: 2,
  staging: 5,
  staged: 1,
  loading: 7,
  departed: 3,
};
const RISK_LABEL: Record<string, string> = {
  cart_misstaged: "Cart scanned to wrong location",
  foreign_cart: "Foreign cart in this location",
  van_grounded: "Van grounded at VSA",
  stage_late: "Projected to stage late",
  bag_in_aisle: "Bag left in aisle",
  depart_late: "Past departure time",
};
const RISK_ICON: Record<string, string> = {
  cart_misstaged: "⇄",
  foreign_cart: "!",
  van_grounded: "✕",
  stage_late: "⏱",
  bag_in_aisle: "◼",
  depart_late: "⏱",
};

export function StagingFloor({ s }: { s: LiveState }) {
  const f = s.views.staging_floor;
  const [sel, setSel] = useState<string | null>(null);
  const [wave, setWave] = useState<number | "all">("all");
  const selected = f.locations.find((l) => l.location === sel) ?? null;
  return (
    <div className="fp">
      <div className="fp__waves" data-testid="wave-strip">
        <button className="fp__wave" aria-pressed={wave === "all"} onClick={() => setWave("all")}>
          All waves
        </button>
        {f.waves.map((w) => (
          <button key={w.wave} className="fp__wave" aria-pressed={wave === w.wave} onClick={() => setWave(w.wave)}>
            <strong>W{w.wave}</strong> {w.stage_by}
            <span className="muted">
              {" "}
              {w.staged + w.departed}/{w.routes}
            </span>
            {w.at_risk > 0 && <span className="fp__risk-count">{w.at_risk}</span>}
          </button>
        ))}
      </div>
      <div className="fp__scroll">
        <div className="fp__floor" data-testid="staging-floor">
          {f.rows.map((row) => (
            <div key={row} className="fp__lane">
              <div className="fp__lane-label">Row {row}</div>
              <div className="fp__slots">
                {f.locations
                  .filter((l) => l.row === row)
                  .sort((a, b) => a.slot - b.slot)
                  .map((l) => (
                    <Slot key={l.location} l={l} dim={wave !== "all" && l.wave !== wave} active={sel === l.location} onClick={() => setSel(l.location === sel ? null : l.location)} />
                  ))}
              </div>
            </div>
          ))}
          <div className="fp__dock">Launch pad / loading lanes → yard (VSA)</div>
        </div>
      </div>
      <div className="fp__legend">
        {Object.entries(SLOT).map(([k, v]) => (
          <span key={k}>
            <i style={{ background: `var(--series-${v})` }} />
            {STATUS_LABEL[k]}
          </span>
        ))}
        {Object.entries(RISK_LABEL).map(([k, v]) => (
          <span key={k}>
            <b className="fp__badge">{RISK_ICON[k]}</b>
            {v}
          </span>
        ))}
      </div>
      {selected && <SlotDetail l={selected} />}
    </div>
  );
}

function Slot({ l, dim, active, onClick }: { l: StagingLoc; dim: boolean; active: boolean; onClick: () => void }) {
  const fill = `var(--series-${SLOT[l.status]})`;
  const pct = l.carts ? l.carts_staged / l.carts : 0;
  return (
    <button
      className={`fp__slot${l.risk ? " fp__slot--risk" : ""}${dim ? " fp__slot--dim" : ""}${active ? " fp__slot--active" : ""}`}
      onClick={onClick}
      title={`${l.location} · ${l.route_id} · ${STATUS_LABEL[l.status]} · wave ${l.wave} · carts ${l.carts_staged}/${l.carts}${l.risk ? ` · ${RISK_LABEL[l.risk]}` : ""}`}
      aria-label={`${l.location} ${l.route_id} ${STATUS_LABEL[l.status]}${l.risk ? ` ${RISK_LABEL[l.risk]}` : ""}`}
      data-testid={`slot-${l.location}`}
    >
      <span className="fp__slot-bar" style={{ background: fill, opacity: l.status === "departed" ? 0.35 : 1 }} />
      <span className="fp__slot-loc">{l.location.replace("STG-", "")}</span>
      <span className="fp__slot-route">{l.route_id.replace("R-", "")}</span>
      {l.carts > 0 && l.status !== "departed" && (
        <span className="fp__carts" aria-hidden>
          <span style={{ width: `${pct * 100}%` }} />
        </span>
      )}
      {l.risk && <b className="fp__badge fp__badge--on">{RISK_ICON[l.risk]}</b>}
    </button>
  );
}

function SlotDetail({ l }: { l: StagingLoc }) {
  return (
    <div className="fp__detail" role="region" aria-label={`${l.location} detail`} data-testid="slot-detail">
      <div>
        <strong>{l.location}</strong> · {l.route_id} · wave {l.wave} · {l.dsp} · <Pill value={l.status} label={STATUS_LABEL[l.status]} />
      </div>
      <div className="muted">
        Stage by {l.stage_by} · depart {l.depart} · carts {l.carts_staged}/{l.carts}
        {l.hv_pending ? ` · ${l.hv_pending} HV pending` : ""} · driver {l.driver ?? "—"} ({l.driver_state?.replace(/_/g, " ") ?? "—"})
      </div>
      {l.risk && <div className="fp__detail-risk">{RISK_LABEL[l.risk]}{l.misstaged_at ? ` — cart is in ${l.misstaged_at}` : ""}{l.foreign_cart ? ` — ${l.foreign_cart}'s cart is here` : ""}</div>}
      <div className="act">
        {l.misstaged_at && <ActButton action={{ kind: "restage_cart", target: l.route_id }} label="Restage cart" variant="primary" testId={`restage-${l.route_id}`} />}
        {l.foreign_cart && <ActButton action={{ kind: "restage_cart", target: l.foreign_cart }} label={`Move ${l.foreign_cart}'s cart`} variant="primary" />}
        {l.risk === "van_grounded" && <ActButton action={{ kind: "request_replacement_van", target: l.route_id }} label="Request replacement van" variant="primary" />}
        {(l.status === "not_ready" || l.status === "ready") && <ActButton action={{ kind: "prioritize_route", target: l.route_id, amount: 1 }} label="Prioritise pick" />}
        {l.status !== "departed" && <ActButton action={{ kind: "notify_drivers", target: l.route_id }} label="Notify driver" />}
      </div>
    </div>
  );
}

export function AislePlan({ s }: { s: LiveState }) {
  const a = s.views.aisle_plan;
  const [sel, setSel] = useState<string | null>(null);
  const cell = a.aisles.find((x) => x.aisle === sel) ?? null;
  return (
    <div className="fp">
      <div className="fp__scroll">
        <div className="ap" data-testid="aisle-plan">
          {a.clusters.map((c) => (
            <div key={c} className="ap__cluster">
              <div className="fp__lane-label">Cluster {c}</div>
              <div className="ap__aisles">
                {a.aisles
                  .filter((x) => x.cluster === c)
                  .map((x) => (
                    <Aisle key={x.aisle} x={x} active={sel === x.aisle} onClick={() => setSel(x.aisle === sel ? null : x.aisle)} />
                  ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="fp__legend">
        <span>
          <i className="ap__legend-fill" /> Bay fill (stowed / capacity)
        </span>
        {(["not_ready", "ready", "picking", "staging", "staged", "departed"] as const).map((k) => (
          <span key={k}>
            <i style={{ background: `var(--series-${SLOT[k]})` }} />
            {STATUS_LABEL[k]}
          </span>
        ))}
        <span>
          <b className="ap__person">P</b> picker · <b className="ap__person ap__person--sweep">S</b> sweeper
        </span>
        <span>
          <b className="fp__badge">◼</b> flagged left-behind
        </span>
      </div>
      {cell && <AisleDetail x={cell} />}
    </div>
  );
}

function Aisle({ x, active, onClick }: { x: AisleCell; active: boolean; onClick: () => void }) {
  const fill = x.capacity ? Math.min(1, x.level / x.capacity) : 0;
  return (
    <button
      className={`ap__aisle${active ? " fp__slot--active" : ""}${x.flagged_left_behind ? " fp__slot--risk" : ""}`}
      onClick={onClick}
      title={`${x.aisle} · ${x.level}/${x.capacity} in bays · ${x.picked}/${x.routes.length} routes picked${x.sweep ? ` · sweep ${x.sweep}` : ""}`}
      aria-label={`Aisle ${x.aisle}`}
      data-testid={`aisle-${x.aisle}`}
    >
      <span className="ap__name">{x.aisle}</span>
      <span className="ap__rack">
        <span className="ap__rack-fill" style={{ height: `${fill * 100}%` }} />
      </span>
      <span className="ap__routes">
        {x.routes.map((r) => (
          <i key={r.route_id} style={{ background: `var(--series-${SLOT[r.status] ?? 8})` }} title={`${r.route_id} ${STATUS_LABEL[r.status] ?? r.status}`} />
        ))}
      </span>
      <span className="ap__people">
        {x.people.map((p) => (
          <b key={p.login} className={`ap__person${p.task.startsWith("sweep") ? " ap__person--sweep" : ""}`} title={`${p.login} · ${p.task}`}>
            {p.task.startsWith("sweep") ? "S" : "P"}
          </b>
        ))}
      </span>
      <span className={`ap__sweep ap__sweep--${x.sweep ?? "none"}`}>{x.sweep === "swept" ? "✓" : x.sweep === "sweeping" ? "…" : x.sweep === "due" ? "•" : ""}</span>
      {x.flagged_left_behind > 0 && <b className="fp__badge fp__badge--on">◼</b>}
    </button>
  );
}

function AisleDetail({ x }: { x: AisleCell }) {
  return (
    <div className="fp__detail" data-testid="aisle-detail">
      <div>
        <strong>Aisle {x.aisle}</strong> · bays {x.level}/{x.capacity} · routes {x.routes.map((r) => `${r.route_id} (${STATUS_LABEL[r.status] ?? r.status}, W${r.wave})`).join(", ")}
      </div>
      <div className="muted">
        In aisle: {x.people.length ? x.people.map((p) => `${p.login} (${p.task.replace(/_/g, " ")})`).join(", ") : "nobody"} · sweep{" "}
        {x.sweep ?? "not due"}
        {x.swept_at ? ` (last ${x.swept_at})` : ""}
        {x.flagged_left_behind ? ` · ${x.flagged_left_behind} package(s) flagged left behind` : ""}
      </div>
      <div className="act">
        <ActButton action={{ kind: "direct_sweep", target: x.aisle }} label="Send sweeper now" variant={x.flagged_left_behind ? "primary" : "default"} testId={`sweep-${x.aisle}`} />
      </div>
    </div>
  );
}
