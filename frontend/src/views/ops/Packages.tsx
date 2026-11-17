// Package summary (live): dwell by cycle / by scheduled delivery window,
// ageing by status and age with in-station / on-road scrubs and missing /
// lost review, RTS by type, and search for packages, containers (routes)
// and associates.
import { useQuery } from "@tanstack/react-query";
import { type FormEvent, Fragment, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { type LiveState, runtimeApi } from "../../api/runtime";
import { Card } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
import { DataUpdated } from "../../components/DataUpdated";
import { StatusTree } from "../../components/StatusTree";
import { ActButton, LiveGate, Pill, Stat, StatRow, Tabs } from "../../components/live";

const TABS = ["Dwell", "Ageing", "RTS", "Search"] as const;
type Tab = (typeof TABS)[number];

export function Packages() {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.toLowerCase() === params.get("tab")) ?? "Dwell") as Tab;
  return (
    <div>
      <PageHeader eyebrow="Package summary" title="Package Summary" badges={<DataSourceBadge kind="simulated" />}>
        Where every package is right now, how long it has been there, and what is coming back.
      </PageHeader>
      <Tabs tabs={TABS} value={tab} onChange={(t) => setParams({ tab: t.toLowerCase() })} />
      {tab === "Search" ? <Search initial={params.get("q") ?? ""} /> : <LiveGate>{(s) => (tab === "Dwell" ? <Dwell s={s} /> : tab === "Ageing" ? <Ageing s={s} /> : <Rts s={s} />)}</LiveGate>}
    </div>
  );
}

function Dwell({ s }: { s: LiveState }) {
  const [by, setBy] = useState<"cycle" | "window">("cycle");
  const t = by === "cycle" ? s.views.dwell_v2.by_cycle : s.views.dwell_v2.by_window;
  return (
    <Card
      title="Dwell"
      actions={
        <div className="seg" role="group" aria-label="Dwell view">
          <button aria-pressed={by === "cycle"} onClick={() => setBy("cycle")}>By cycle</button>
          <button aria-pressed={by === "window"} onClick={() => setBy("window")}>By scheduled delivery window</button>
        </div>
      }
    >
      <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
        Every package is in exactly one status. Expand a group for its sub-statuses; every count opens the packages
        behind it. {t.total.toLocaleString()} packages in today's tree.
      </p>
      <StatusTree
        key={by}
        testId={by === "cycle" ? "dwell-cycle" : "dwell-window"}
        columns={t.columns}
        groups={t.groups}
        drill={(group, status, column) => ({ group, status, column, by })}
        clock={s.snapshot.clock}
      />
    </Card>
  );
}

function Ageing({ s }: { s: LiveState }) {
  const a = s.views.ageing_v2;
  const [leg, setLeg] = useState<"forward" | "reverse">("forward");
  const [review, setReview] = useState<"missing" | "lost" | null>(null);
  const list = review === "missing" ? a.missing_packages : review === "lost" ? a.lost_packages : [];
  // Lists exist for packages in today's tree (the dwell groups); carried-over
  // retained / missing / lost rows have their own review lists below.
  const listable = new Set(s.views.dwell_v2.by_cycle.groups.map((g) => g.group));
  return (
    <div className="stack">
      <div className="toolbar-inline">
        <ActButton action={{ kind: "start_scrub", target: "in_station" }} label="Start in-station scrub" variant="primary" testId="scrub-in-station" />
        <ActButton action={{ kind: "start_scrub", target: "on_road" }} label="Start on-road scrub" variant="primary" />
        <span className="muted" style={{ fontSize: 12 }}>A scrub assumes the associate has completed the physical search.</span>
      </div>
      <div className="toolbar-inline">
        <button className="button button--sm" onClick={() => setReview("missing")} data-testid="review-missing">
          Review missing packages ({a.missing_packages.length})
        </button>
        <button className="button button--sm" onClick={() => setReview("lost")} data-testid="review-lost">
          Review lost packages ({a.lost_packages.length})
        </button>
        {a.scrubs.map((sc, i) => (
          <Pill key={i} value="running" label={`${sc.kind.replace("_", "-")} scrub: ${sc.resolved} resolved`} />
        ))}
      </div>
      {review && (
        <Card title={review === "missing" ? "Missing packages" : "Lost packages (4+ days)"} actions={<button className="button button--sm" onClick={() => setReview(null)}>Close</button>}>
          <DataTable
            columns={[
              { key: "tracking_id", label: "Tracking ID", filter: true },
              { key: "status", label: "Status", value: (r) => r.status.replace(/_/g, " ") },
              { key: "age_days", label: "Age (days)", num: true },
              { key: "resolution", label: "Resolution", value: (r) => r.resolution ?? "open" },
            ]}
            rows={list}
            rowKey={(r) => r.tracking_id}
            maxHeight={320}
          />
        </Card>
      )}
      <Card
        title={`Ageing — ${leg} leg`}
        actions={
          <div className="seg" role="group" aria-label="Leg">
            <button aria-pressed={leg === "forward"} onClick={() => setLeg("forward")}>Forward (delivery)</button>
            <button aria-pressed={leg === "reverse"} onClick={() => setLeg("reverse")}>Reverse (returns)</button>
          </div>
        }
      >
        <StatusTree
          key={leg}
          testId="ageing"
          columns={a.buckets}
          groups={a[leg]}
          totalKey="total"
          drill={(group, status, column) => (leg === "forward" && column === undefined && listable.has(group) ? { group, status } : null)}
          clock={s.snapshot.clock}
        />
        <p className="muted" style={{ fontSize: 12 }}>
          Days in status come from each package's status-since time across chained days. Totals of today's statuses
          open the package list.
        </p>
      </Card>
    </div>
  );
}

function Rts({ s }: { s: LiveState }) {
  const r = s.views.rts;
  return (
    <div className="stack">
      <StatRow>
        <Stat label="Inbound (returning on vans)" value={r.totals.inbound} />
        <Stat label="Currently at station" value={r.totals.at_station} />
        <Stat label="Delivery cancelled" value={r.delivery_cancelled} sub="damaged / held" />
      </StatRow>
      <Card title="Returns to station by type">
        <table data-testid="rts-table">
          <thead>
            <tr>
              <th>Status</th>
              {r.types.map((t) => (
                <th key={t} className="num">
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <strong>Inbound</strong>
              </td>
              {r.types.map((t) => (
                <td key={t} className="num tabular">
                  {r.inbound[t] ?? 0}
                </td>
              ))}
            </tr>
            <tr>
              <td>
                <strong>Currently at station</strong>
              </td>
              {r.types.map((t) => (
                <td key={t} className="num tabular">
                  {r.currently_at_station[t] ?? 0}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
        <DataUpdated clock={s.snapshot.clock} />
      </Card>
    </div>
  );
}

function Search({ initial }: { initial: string }) {
  const [text, setText] = useState(initial);
  const [q, setQ] = useState(initial);
  const res = useQuery({ queryKey: ["search", q], queryFn: () => runtimeApi.search(q), enabled: q.length > 0 });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setQ(text.trim());
  };
  return (
    <Card title="Search packages, containers or associates">
      <form className="toolbar-inline" onSubmit={submit}>
        <input aria-label="Search query" value={text} onChange={(e) => setText(e.target.value)} placeholder="PKG…, GAYLORD_…, R-012, assoc…" style={{ minWidth: 260 }} />
        <button className="button button--primary" type="submit">
          Search
        </button>
      </form>
      {res.data && res.data.kind === "none" && <p className="muted">No match.</p>}
      {res.data && res.data.kind !== "none" && (
        <div data-testid="search-results" className="stack">
          <p className="muted">
            {res.data.results.length} {res.data.kind === "container_v2" ? "container" : res.data.kind} result(s)
          </p>
          {res.data.results.map((r, i) =>
            res.data!.kind === "container_v2" ? (
              <ContainerResult key={i} r={r as unknown as ContainerHit} />
            ) : res.data!.kind === "associate" ? (
              <AssociateResult key={i} r={r as unknown as AssociateHit} />
            ) : res.data!.kind === "package" ? (
              <PackageResult key={i} r={r as unknown as PackageHit} />
            ) : (
              <GenericResult key={i} r={r} />
            ),
          )}
        </div>
      )}
    </Card>
  );
}

type TimelineEv = { event: string; clock: string; actor?: string };
interface ContainerHit {
  id: string;
  type: string;
  linehaul: string;
  origin: string;
  total: number;
  pending_induct: number;
  inducted: number;
  stowed: number;
  clusters: Record<string, number>;
  timeline: TimelineEv[];
}
interface AssociateHit {
  login: string;
  role: string;
  home_role: string;
  present: boolean;
  task: string;
  location: string | null;
  shift_start: string | null;
  activity?: { clock: string; role: string; until: string | null }[];
  inducted?: number;
  stowed?: number;
  fsaf?: number;
  spot_checks?: number;
  units?: number;
}
interface PackageHit {
  tracking_id: string;
  status: string;
  route_id: string | null;
  cycle: string;
  location: string | null;
  container?: string | null;
  planned?: boolean;
  ps_state?: string | null;
  misdivert?: string | null;
  line?: string | null;
  inducted_by?: string | null;
  stowed_by?: string | null;
  high_value?: boolean;
  timeline?: TimelineEv[];
  [k: string]: unknown;
}

const label = (k: string) => k.replace(/_/g, " ");

function Timeline({ items, testId }: { items: TimelineEv[]; testId?: string }) {
  return (
    <ol className="legs" data-testid={testId} style={{ marginTop: 8 }}>
      {items.map((t, i) => (
        <li key={`${t.event}-${i}`} className="legs--done">
          <span className="tabular">{t.clock}</span> {t.event}
          {t.actor && <span className="muted"> · {t.actor}</span>}
        </li>
      ))}
    </ol>
  );
}

function ContainerResult({ r }: { r: ContainerHit }) {
  return (
    <div className="search-result" data-testid="search-container">
      <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>
        {r.type === "GAYLORD" ? "Gaylord" : r.type === "PALLET" ? "Pallet" : r.type} {r.id}
      </h3>
      <StatRow>
        <Stat label="Pending induct" value={r.pending_induct} sub={`of ${r.total}`} />
        <Stat label="Inducted" value={r.inducted} />
        <Stat label="Stowed" value={r.stowed} />
        <Stat label="Linehaul" value={<span style={{ fontSize: 16 }}>{r.linehaul}</span>} sub={r.origin} />
      </StatRow>
      <p className="muted" style={{ margin: 0 }}>
        Clusters: {Object.entries(r.clusters ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"}
      </p>
      <Timeline items={r.timeline ?? []} testId="container-timeline" />
    </div>
  );
}

function AssociateResult({ r }: { r: AssociateHit }) {
  return (
    <div className="search-result" data-testid="search-associate">
      <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>
        {r.login} <Pill value={r.present ? "running" : "neutral"} label={r.present ? "present" : "absent"} />
      </h3>
      <dl className="kv">
        <dt>Current path</dt>
        <dd>{label(r.role)} (home: {label(r.home_role)})</dd>
        <dt>Task / location</dt>
        <dd>
          {label(r.task)} · {r.location ?? "—"}
        </dd>
        <dt>Shift start</dt>
        <dd>{r.shift_start ?? "—"}</dd>
      </dl>
      <StatRow>
        <Stat label="Inducted" value={r.inducted ?? 0} />
        <Stat label="Stowed" value={r.stowed ?? 0} />
        {r.fsaf !== undefined && <Stat label="FSAF" value={r.fsaf} sub={`${r.spot_checks ?? 0} spot checks`} />}
        {r.units !== undefined && <Stat label="Units" value={r.units} />}
      </StatRow>
      <h4 className="page-section-title">Activity</h4>
      <ol className="legs" data-testid="associate-activity">
        {(r.activity ?? []).map((a, i) => (
          <li key={i} className={a.until ? "legs--done" : "legs--active"}>
            <strong>{label(a.role)}</strong>{" "}
            <span className="tabular muted">
              {a.clock} – {a.until ?? "now"}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function PackageResult({ r }: { r: PackageHit }) {
  const fields: [string, unknown][] = [
    ["Status", label(r.status)],
    ["Cycle", r.cycle],
    ["Route", r.route_id],
    ["Location", r.location],
    ["Container", r.container],
    ["Planned", r.planned === undefined ? undefined : r.planned ? "Planned (in container plan)" : "Unplanned"],
    ["Induct line", r.line],
    ["Inducted by", r.inducted_by],
    ["Stowed by", r.stowed_by],
    ["PS state", r.ps_state ? label(r.ps_state) : "none"],
    ["Misdivert", r.misdivert ? label(r.misdivert) : "none"],
  ];
  return (
    <div className="search-result" data-testid="search-package">
      <h3 style={{ margin: "0 0 6px", fontSize: 14 }}>
        {r.tracking_id} {r.high_value && <Pill value="planned" label="High value" />}
      </h3>
      <dl className="kv">
        {fields.map(([k, v]) => (
          <Fragment key={k}>
            <dt>{k}</dt>
            <dd>{v === null || v === undefined || v === "" ? "—" : String(v)}</dd>
          </Fragment>
        ))}
      </dl>
      {Array.isArray(r.timeline) && <Timeline items={r.timeline} testId="package-timeline" />}
    </div>
  );
}

function GenericResult({ r }: { r: Record<string, unknown> }) {
  return (
    <div className="search-result">
      <table>
        <tbody>
          {Object.entries(r)
            .filter(([k, v]) => k !== "timeline" && k !== "rotation" && k !== "activity" && (v === null || typeof v !== "object"))
            .map(([k, v]) => (
              <tr key={k}>
                <td className="muted" style={{ width: 180 }}>
                  {label(k)}
                </td>
                <td>
                  <strong>{v === null || v === undefined ? "—" : String(v)}</strong>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
      {Array.isArray(r.timeline) && <Timeline items={r.timeline as TimelineEv[]} />}
    </div>
  );
}
