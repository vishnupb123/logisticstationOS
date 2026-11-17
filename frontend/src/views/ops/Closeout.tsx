// Close-out & Tomorrow (live): after every route departs, associates go home
// and a supervisor and a manager close the day — GTDRs for irregular trailers,
// ferry checks and the (never truly final) truckfile, in-station and on-road
// scrubs — and plan tomorrow: OFD volume, SPR, TPH, needed vs expected
// headcount, VET/VTO offers that associates choose to accept, aisle volume
// division and task assignment with job rotation. Everything is simulated.
import { useState } from "react";
import type { Closeout as CloseoutT, CloseoutTask, Gtdr, LiveState } from "../../api/runtime";
import { pctv, runtimeApi, useStation } from "../../api/runtime";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "../../components/Card";
import { type Column, DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { ActButton, LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";
import "./Closeout.css";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "truckfile", label: "Truckfile" },
  { key: "gtdr", label: "GTDR" },
  { key: "labor", label: "Headcount · VET / VTO" },
  { key: "plan", label: "Tomorrow's plan" },
  { key: "scrubs", label: "Scrubs & sweep" },
] as const;
type Tab = (typeof TABS)[number]["key"];
const SHORT: Record<string, string> = { induct: "IND", stow: "STW", pick: "PCK", problem_solve: "PS", high_value: "HV" };

export function Closeout() {
  const [tab, setTab] = useState<Tab>("overview");
  return (
    <div>
      <PageHeader eyebrow="After dispatch" title="Close-out & Tomorrow" badges={<DataSourceBadge kind="simulated" />}>
        Once every route has departed, associates finish their shift and the supervisor and manager close the day and
        plan the next one. The truckfile is never truly final — revisions keep arriving after it is published, and a
        ferry change is only learned when someone checks.
      </PageHeader>
      <LiveGate>
        {(s) => (
          <div className="stack">
            <Tabs tabs={TABS} value={tab} onChange={(t) => setTab(t as Tab)} />
            {!s.views.closeout.started ? (
              <NotStarted s={s} />
            ) : tab === "overview" ? (
              <Overview c={s.views.closeout} />
            ) : tab === "truckfile" ? (
              <TruckfileTab c={s.views.closeout} />
            ) : tab === "gtdr" ? (
              <GtdrTab c={s.views.closeout} />
            ) : tab === "labor" ? (
              <LaborTab c={s.views.closeout} />
            ) : tab === "plan" ? (
              <PlanTab c={s.views.closeout} />
            ) : (
              <ScrubTab s={s} />
            )}
          </div>
        )}
      </LiveGate>
    </div>
  );
}

function NotStarted({ s }: { s: LiveState }) {
  const left = s.snapshot.routes.filter((r) => r.status !== "departed" && !r.sidelined).length;
  return (
    <Card title="Close-out hasn't started">
      <p className="muted" data-testid="closeout-pending">
        It starts when the last route departs — {left} route(s) still to go (now {s.snapshot.clock}). Then associates go
        home (sweepers finish their aisles first) and the supervisor and manager take over. Speed the day up from the
        session bar to get there faster.
      </p>
    </Card>
  );
}

function NextDayButton() {
  const qc = useQueryClient();
  const live = useStation();
  const s = live.data?.session;
  const m = useMutation({
    mutationFn: () => runtimeApi.create({ source: "next_day", mode: s?.mode ?? "autopilot", speed: s?.speed ?? 2 }),
    onSuccess: () => qc.invalidateQueries(),
  });
  if (!s?.next_day_ready) return null;
  return (
    <button className="button button--primary" onClick={() => m.mutate()} disabled={m.isPending} data-testid="run-next-day">
      {m.isPending ? "Starting…" : `▶ Run day ${s.day + 1} from truckfile v${live.data?.views.closeout.truckfile.version}`}
    </button>
  );
}

function ActionsBar() {
  return (
    <div className="toolbar-inline">
      <NextDayButton />
      <ActButton action={{ kind: "check_ferry" }} label="Check ferries now" testId="co-check-ferry" />
      <ActButton action={{ kind: "replan_next_day" }} label="Re-plan tomorrow" variant="primary" testId="co-replan" />
      <ActButton action={{ kind: "offer_vet", amount: 2 }} label="Offer VET to 2 more" />
      <ActButton action={{ kind: "offer_vto", amount: 2 }} label="Offer VTO to 2" />
      <ActButton action={{ kind: "draft_gtdr" }} label="Pre-draft GTDRs" />
    </div>
  );
}

function Overview({ c }: { c: CloseoutT }) {
  const tf = c.truckfile;
  const plan = c.plan;
  const stale = plan && plan.truckfile_version !== tf.version;
  return (
    <div className="stack" data-testid="closeout-overview">
      <StatRow>
        <Stat label="Tomorrow OFD volume" value={c.ofd ? c.ofd.ofd_volume.toLocaleString() : "—"} sub={c.ofd ? `${c.ofd.carryover.toLocaleString()} carry-over` : undefined} />
        <Stat label="Routes · SPR" value={c.needs ? `${c.needs.routes} · ${c.needs.spr}` : "—"} sub={c.needs ? `TPH ${c.needs.tph.toLocaleString()}` : undefined} />
        <Stat label="Need vs expected" value={c.needs && c.show ? `${c.needs.headcount} / ${c.show.expected}` : "—"} sub={c.gap != null ? (c.gap > 0 ? `short ${c.gap}` : `over ${-c.gap}`) : undefined} />
        <Stat label="Truckfile" value={tf.version ? `v${tf.version}` : "draft"} sub={tf.final_published_at ? `final ${tf.final_published_at}` : `final due ${tf.final_due}`} />
        <Stat label="Plan" value={plan ? `v${plan.version}` : "—"} sub={plan ? (stale ? <span className="late">on stale truckfile v{plan.truckfile_version}</span> : `on truckfile v${plan.truckfile_version}`) : "built after 18:00"} />
        <Stat label="GTDR open" value={c.gtdr.filter((g) => g.status !== "filed").length} sub={`${c.gtdr.length} today`} />
      </StatRow>
      <ActionsBar />
      {c.complete && c.readiness && (
        <Card title="Readiness for tomorrow (judged against the full truth)">
          <StatRow>
            <Stat label="True OFD volume" value={Number(c.readiness.true_ofd_volume).toLocaleString()} sub={`planned ${Number(c.readiness.planned_ofd_volume ?? 0).toLocaleString()}`} />
            <Stat label="Staffing gap" value={String(c.readiness.staffing_gap)} sub={`need ${c.readiness.true_headcount_needed}, expected ${c.readiness.expected_show}`} />
            <Stat label="Plan on latest truckfile" value={c.readiness.plan_on_latest_truckfile ? "yes" : "no"} />
            <Stat label="Unrevealed revisions" value={String(c.readiness.unrevealed_revisions)} />
            <Stat label="Rotation compliance" value={pctv(c.readiness.rotation_compliance as number | null, 0)} />
          </StatRow>
          <p className="muted" style={{ fontSize: 12 }}>
            Proposed readiness measure (not an organisational metric): how far the plan's headcount and volume are from
            what tomorrow's complete truckfile implies.
          </p>
        </Card>
      )}
      <div className="grid-2">
        <TaskQueue title="Supervisor" tasks={c.tasks.filter((t) => t.owner === "supervisor")} />
        <TaskQueue title="Manager" tasks={c.tasks.filter((t) => t.owner === "manager")} />
      </div>
    </div>
  );
}

function TaskQueue({ title, tasks }: { title: string; tasks: CloseoutTask[] }) {
  const active = tasks.filter((t) => t.status !== "done");
  const done = tasks.filter((t) => t.status === "done").slice(-12).reverse();
  return (
    <Card title={`${title} — ${active.length} open`}>
      <ul className="co-tasks" data-testid={`tasks-${title.toLowerCase()}`}>
        {active
          .sort((a, b) => (a.status === "in_progress" ? -1 : b.status === "in_progress" ? 1 : a.priority - b.priority))
          .map((t) => (
            <li key={t.id} className={`co-task co-task--${t.status}`}>
              <Pill value={t.status === "in_progress" ? "running" : "planned"} label={t.status === "in_progress" ? "doing" : `P${t.priority}`} />
              <span>{t.title}</span>
              <span className="muted tabular">{t.created_clock}</span>
            </li>
          ))}
        {done.map((t) => (
          <li key={t.id} className="co-task co-task--done">
            <span className="co-check">✓</span>
            <span>
              {t.title}
              {t.result && <span className="muted"> — {t.result}</span>}
            </span>
            <span className="muted tabular">{t.finished_clock}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function TruckfileTab({ c }: { c: CloseoutT }) {
  const tf = c.truckfile;
  type TripRow = CloseoutT["truckfile"]["trips"][number];
  const cols: Column<TripRow>[] = [
    { key: "trip_id", label: "Trip", filter: true, render: (t) => <>{t.trip_id}{t.added && <span className="pill pill--warn" style={{ marginLeft: 4 }}>added</span>}</> },
    { key: "origin", label: "Origin", filter: true },
    { key: "sailing", label: "Ferry sailing", value: (t) => t.sailing ?? "road" },
    { key: "planned_arrival", label: "Planned" },
    { key: "eta", label: "ETA (known)", render: (t) => (t.delay_minutes > 0 ? <strong className="late">{t.eta}</strong> : t.eta) },
    { key: "delay_minutes", label: "Delay", num: true, render: (t) => (t.delay_minutes ? `${t.delay_minutes} min` : "—") },
    { key: "volume", label: "Volume", num: true },
    { key: "status", label: "Status", value: (t) => (t.cancelled ? "cancelled" : t.after_pick_start ? "after pick start" : "in time"), render: (t) => <Pill value={t.cancelled ? "cancelled" : t.after_pick_start ? "planned" : "running"} label={t.cancelled ? "cancelled" : t.after_pick_start ? "rollover risk" : "in time"} /> },
    { key: "last_checked", label: "Last ferry check", value: (t) => (t.via_ferry ? t.last_checked ?? "never" : "—") },
  ];
  return (
    <div className="stack">
      <ActionsBar />
      <Card title={`Tomorrow's truckfile — ${tf.version ? `v${tf.version}` : "draft"}`}>
        <DataTable testId="tomorrow-truckfile" columns={cols} rows={tf.trips} rowKey={(t) => t.trip_id} rowClass={(t) => (t.cancelled ? "row-risk" : t.after_pick_start ? "row-warn" : undefined)} maxHeight={420} />
      </Card>
      <div className="grid-2">
        <Card title="Revisions">
          {tf.log.length === 0 ? (
            <p className="muted">No revisions yet.</p>
          ) : (
            <ul className="cc-iv-list" data-testid="truckfile-log">
              {[...tf.log].reverse().map((l, i) => (
                <li key={i} className={l.after_final ? "co-after-final" : undefined}>
                  <span className="tabular">{l.clock}</span> {l.trip_id}: {l.field} {String(l.before)} → <strong>{String(l.after)}</strong> — {l.why}{" "}
                  <span className="muted">({l.how}{l.after_final ? `, after final → v${l.version}` : ""})</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Ferry status checks">
          <ul className="cc-iv-list">
            {[...tf.ferry_checks].reverse().map((f, i) => (
              <li key={i}>
                <span className="tabular">{f.clock}</span> {f.changes ? <strong>{f.changes} change(s)</strong> : "no changes"}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function GtdrTab({ c }: { c: CloseoutT }) {
  const cols: Column<Gtdr>[] = [
    { key: "gtdr_id", label: "GTDR" },
    { key: "direction", label: "Direction", filter: true, value: (g) => (g.direction === "inbound_late" ? "late inbound" : "outbound pallet") },
    { key: "trailer", label: "Trailer" },
    { key: "place", label: "Origin / destination" },
    { key: "scheduled", label: "Scheduled" },
    { key: "actual", label: "Actual" },
    { key: "delay_minutes", label: "Delay", num: true, render: (g) => (g.delay_minutes ? `${g.delay_minutes} min` : "—") },
    { key: "units", label: "Units", num: true },
    { key: "pallets", label: "Pallets", num: true },
    { key: "seal", label: "Seal" },
    { key: "reason", label: "Reason" },
    { key: "status", label: "Status", filter: true, render: (g) => <Pill value={g.status === "filed" ? "finished" : g.status === "drafted" ? "staging" : "jam"} label={g.status} /> },
    { key: "filed_clock", label: "Filed", value: (g) => g.filed_clock ?? "—" },
  ];
  return (
    <div className="stack">
      <p className="muted" style={{ fontSize: 13 }}>
        GTDR — Global Trailer Dock and Release: the supervisor's record of an irregular trailer at the dock (a late inbound
        truck or an outbound pallet truck released from the site). The field set is a proposed, generic one.
      </p>
      <div className="toolbar-inline">
        <ActButton action={{ kind: "draft_gtdr" }} label="Pre-draft GTDRs from trailer data" variant="primary" />
      </div>
      <Card title="GTDR records">
        <DataTable testId="gtdr-table" columns={cols} rows={c.gtdr} rowKey={(g) => g.gtdr_id} rowClass={(g) => (g.status === "open" ? "row-warn" : undefined)} empty="No irregular trailers today." />
      </Card>
    </div>
  );
}

function LaborTab({ c }: { c: CloseoutT }) {
  const o = c.ofd;
  const n = c.needs;
  const sh = c.show;
  return (
    <div className="stack">
      <ActionsBar />
      {o && n && sh && (
        <div className="grid-2">
          <Card title="Volume → needs">
            <table className="co-kv">
              <tbody>
                <tr><td>Linehaul arriving before pick start</td><td className="tabular">{o.linehaul_in_time.toLocaleString()}</td></tr>
                <tr><td>Carry-over (rollover {o.rollover}, cluster transfer {o.cluster_transfer}, re-attempt {o.reattempt}, late trailer {o.late_trailer})</td><td className="tabular">{o.carryover.toLocaleString()}</td></tr>
                <tr><td><strong>Predicted OFD volume</strong></td><td className="tabular"><strong>{o.ofd_volume.toLocaleString()}</strong></td></tr>
                <tr><td>At risk (arrives after pick start)</td><td className="tabular">{o.linehaul_at_risk.toLocaleString()}</td></tr>
                <tr><td>Routes · SPR · TPH</td><td className="tabular">{n.routes} · {n.spr} · {n.tph.toLocaleString()}</td></tr>
                {Object.entries(n.by_role).map(([k, v]) => (
                  <tr key={k}><td>Needed — {k.replace(/_/g, " ")}</td><td className="tabular">{v}</td></tr>
                ))}
                <tr><td><strong>Headcount needed</strong> ({n.labor_hours} labor h)</td><td className="tabular"><strong>{n.headcount}</strong></td></tr>
              </tbody>
            </table>
          </Card>
          <Card title="Expected show">
            <table className="co-kv">
              <tbody>
                <tr><td>Scheduled (after call-outs and VTO)</td><td className="tabular">{sh.scheduled}</td></tr>
                <tr><td>Call-outs</td><td className="tabular">{sh.called_out}</td></tr>
                <tr><td>VET accepted</td><td className="tabular">{sh.vet_accepted}</td></tr>
                <tr><td>VTO accepted</td><td className="tabular">{sh.vto_accepted}</td></tr>
                <tr><td>Offers awaiting an answer</td><td className="tabular">{sh.pending_offers}</td></tr>
                <tr><td><strong>Expected show</strong> (attendance-adjusted)</td><td className="tabular"><strong>{sh.expected}</strong></td></tr>
                <tr><td><strong>Gap</strong></td><td className={`tabular${(c.gap ?? 0) > 1 ? " late" : ""}`}><strong>{c.gap}</strong></td></tr>
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 12 }}>
              VET and VTO are offers: each associate decides. Later VET offers get fewer takers (proposed acceptance
              model).
            </p>
          </Card>
        </div>
      )}
      <Card title={`VET / VTO offers (${c.offers.length})`}>
        <DataTable
          testId="offers-table"
          columns={[
            { key: "login", label: "Associate" },
            { key: "type", label: "Offer", filter: true, value: (x) => x.type.toUpperCase() },
            { key: "offered_clock", label: "Offered" },
            { key: "status", label: "Answer", filter: true, render: (x) => <Pill value={x.status === "accepted" ? "finished" : x.status === "declined" ? "cancelled" : "planned"} label={x.status} /> },
            { key: "responded_clock", label: "Answered", value: (x) => x.responded_clock ?? "—" },
            { key: "source", label: "Offered by" },
          ]}
          rows={c.offers}
          rowKey={(x) => `${x.login}-${x.type}`}
          empty="No offers yet — the manager sends them after the final truckfile."
          maxHeight={320}
        />
      </Card>
      <div className="grid-2">
        <Card title="Call-outs for tomorrow">
          {c.callouts.length ? (
            <ul className="cc-iv-list">
              {c.callouts.map((x) => (
                <li key={x.login}>
                  <span className="tabular">{x.clock}</span> {x.login} called out
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">None so far.</p>
          )}
        </Card>
        <Card title="Plan history">
          <DataTable
            columns={[
              { key: "version", label: "Plan", value: (x) => `v${x.version}` },
              { key: "clock", label: "When" },
              { key: "label", label: "Why" },
              { key: "truckfile_version", label: "Truckfile", value: (x) => `v${x.truckfile_version}` },
              { key: "ofd_volume", label: "OFD", num: true },
              { key: "headcount_needed", label: "Need", num: true },
              { key: "expected", label: "Expected", num: true },
              { key: "gap", label: "Gap", num: true },
            ]}
            rows={c.plan_history}
            rowKey={(x) => String(x.version)}
            empty="No plan yet."
          />
        </Card>
      </div>
    </div>
  );
}

function PlanTab({ c }: { c: CloseoutT }) {
  const p = c.plan;
  if (!p) return <Card title="Tomorrow's plan"><p className="muted">The manager builds the plan at 18:00 (or when re-planning is requested after the final truckfile).</p></Card>;
  const max = Math.max(...p.aisles.map((a) => a.volume), 1);
  return (
    <div className="stack" data-testid="tomorrow-plan">
      <StatRow>
        <Stat label="Plan version" value={`v${p.version}`} sub={`${p.clock} · truckfile v${p.truckfile_version}`} />
        <Stat label="OFD volume" value={p.ofd.ofd_volume.toLocaleString()} />
        <Stat label="Routes · SPR" value={`${p.needs.routes} · ${p.needs.spr}`} />
        <Stat label="Stow zones" value={p.zones.length} />
        <Stat label="Rotation compliance" value={pctv(p.rotation_compliance, 0)} sub={`${p.rotation_violations} violation(s)`} />
      </StatRow>
      <Card title="Volume division across aisles">
        <div className="co-bars" role="img" aria-label="Planned volume per aisle">
          {p.aisles.map((a) => (
            <div key={a.aisle} className="co-bar" title={`${a.aisle}: ${a.volume} packages, ${a.routes} route(s)`}>
              <span style={{ height: `${(a.volume / max) * 100}%` }} />
            </div>
          ))}
        </div>
        <div className="co-bars__axis">
          {p.aisles.map((a, i) => (
            <span key={a.aisle}>{i % 5 === 0 ? a.aisle : ""}</span>
          ))}
        </div>
      </Card>
      <div className="grid-2">
        <Card title="Stow zones">
          <DataTable columns={[{ key: "zone", label: "Zone" }, { key: "aisles", label: "Aisles" }, { key: "volume", label: "Volume", num: true }]} rows={p.zones} rowKey={(z) => z.zone} />
        </Card>
        <Card title="Task assignment (job rotation)">
          <DataTable
            testId="assignments-table"
            columns={[
              { key: "where", label: "Task", filter: true },
              { key: "login", label: "Associate", value: (x) => x.login ?? "unfilled" },
              { key: "history", label: "Last 3 days", value: (x) => (x.history?.length ? x.history.map((h) => SHORT[h] ?? h).join("·") : x.vet ? "VET" : "—") },
              { key: "ok", label: "Rotation", render: (x) => (x.ok ? <Pill value="finished" label="ok" /> : <Pill value="jam" label={x.note || "violation"} />) },
            ]}
            rows={p.assignments}
            rowKey={(x) => `${x.where}-${x.login}`}
            rowClass={(x) => (!x.ok ? "row-risk" : undefined)}
            maxHeight={420}
          />
        </Card>
      </div>
    </div>
  );
}

function ScrubTab({ s }: { s: LiveState }) {
  const c = s.views.closeout;
  const a = s.views.aisle_plan;
  return (
    <div className="stack">
      <StatRow>
        <Stat label="Aisles swept" value={a.swept} />
        <Stat label="Recovered to carts by sweep" value={a.sweep_recovered} />
        <Stat label="Cluster transfer (next cycle)" value={a.cluster_transfer} />
        <Stat label="In-station scrub" value={c.scrubs.in_station ? String(c.scrubs.in_station.clock) : "pending"} />
        <Stat label="On-road scrub" value={c.scrubs.on_road ? String(c.scrubs.on_road.clock) : "pending"} sub="after drivers return" />
      </StatRow>
      <div className="toolbar-inline">
        <ActButton action={{ kind: "start_scrub", target: "in_station" }} label="Run in-station scrub now" />
        <ActButton action={{ kind: "start_scrub", target: "on_road" }} label="Run on-road scrub now" />
      </div>
      <div className="grid-2">
        {(["in_station", "on_road"] as const).map((k) => (
          <Card key={k} title={k === "in_station" ? "In-station scrub" : "On-road scrub"}>
            {c.scrubs[k] ? (
              <table className="co-kv">
                <tbody>
                  {Object.entries(c.scrubs[k]).map(([kk, v]) => (
                    <tr key={kk}>
                      <td>{kk.replace(/_/g, " ")}</td>
                      <td>{String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">Not done yet.</p>
            )}
          </Card>
        ))}
      </div>
      <Card title="Sweep log (problem solve walking picked aisles)">
        <DataTable
          testId="sweep-log"
          columns={[
            { key: "clock", label: "When" },
            { key: "aisle", label: "Aisle", filter: true },
            { key: "route_id", label: "Route", filter: true },
            { key: "packages", label: "Packages", num: true },
            { key: "reasons", label: "Why left", value: (x) => x.reasons.join(", ").replace(/_/g, " ") },
            { key: "outcome", label: "Outcome", filter: true, render: (x) => <Pill value={x.outcome === "staged" ? "finished" : "planned"} label={x.outcome === "staged" ? "staged to cart" : "cluster transfer"} /> },
            { key: "by", label: "Sweeper" },
          ]}
          rows={[...a.sweep_log].reverse()}
          rowKey={(x) => `${x.clock}-${x.aisle}-${x.route_id}`}
          empty="Nothing found yet."
          maxHeight={360}
        />
      </Card>
    </div>
  );
}
