// Package summary (live): dwell by cycle / by scheduled delivery window,
// ageing by status and age with in-station / on-road scrubs and missing /
// lost review, RTS by type, and search for packages, containers (routes)
// and associates.
import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { type LiveState, runtimeApi } from "../../api/runtime";
import { Card } from "../../components/Card";
import { DataTable } from "../../components/DataTable";
import { DataSourceBadge } from "../../components/DataSourceBadge";
import { PageHeader } from "../../components/PageHeader";
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

function Matrix({ rows, cols, testId }: { rows: Record<string, string | number>[]; cols: string[]; testId: string }) {
  return (
    <div className="table-scroll">
      <table data-testid={testId}>
        <thead>
          <tr>
            <th>Status</th>
            {cols.map((c) => (
              <th key={c} className="num">
                {c}
              </th>
            ))}
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r.status)}>
              <td>
                <strong>{r.status}</strong>
              </td>
              {cols.map((c) => (
                <td key={c} className="num tabular">
                  {Number(r[c] ?? 0).toLocaleString()}
                </td>
              ))}
              <td className="num tabular">{cols.reduce((a, c) => a + Number(r[c] ?? 0), 0).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Dwell({ s }: { s: LiveState }) {
  const [by, setBy] = useState<"cycle" | "window">("cycle");
  const d = s.views.dwell;
  return (
    <Card
      title="Dwell"
      actions={
        <div className="seg">
          <button aria-pressed={by === "cycle"} onClick={() => setBy("cycle")}>By cycle</button>
          <button aria-pressed={by === "window"} onClick={() => setBy("window")}>By scheduled delivery window</button>
        </div>
      }
    >
      {by === "cycle" ? <Matrix testId="dwell-cycle" rows={d.by_cycle} cols={d.columns} /> : <Matrix testId="dwell-window" rows={d.by_window} cols={d.windows} />}
    </Card>
  );
}

function Ageing({ s }: { s: LiveState }) {
  const a = s.views.ageing;
  const [review, setReview] = useState<"missing" | "lost" | null>(null);
  const list = review === "missing" ? a.missing_packages : review === "lost" ? a.lost_packages : [];
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
        <button className="button button--sm" onClick={() => setReview("lost")}>
          Review lost packages ({a.lost_packages.length})
        </button>
        {a.scrubs.map((sc, i) => (
          <Pill key={i} value="running" label={`${sc.kind.replace("_", "-")} scrub: ${sc.resolved} resolved`} />
        ))}
      </div>
      <Card title="Ageing — forward leg">
        <Matrix testId="ageing" rows={a.rows} cols={a.buckets} />
      </Card>
      {review && (
        <Card title={review === "missing" ? "Missing packages" : "Lost packages (4+ days)"} actions={<button className="button button--sm" onClick={() => setReview(null)}>Close</button>}>
          <DataTable
            columns={[
              { key: "tracking_id", label: "Tracking ID", filter: true },
              { key: "status", label: "Status" },
              { key: "age_days", label: "Age (days)", num: true },
              { key: "resolution", label: "Resolution", value: (r) => r.resolution ?? "open" },
            ]}
            rows={list}
            rowKey={(r) => r.tracking_id}
            maxHeight={320}
          />
        </Card>
      )}
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
    <Card title="Search packages, containers (routes) or associates">
      <form className="toolbar-inline" onSubmit={submit}>
        <input aria-label="Search query" value={text} onChange={(e) => setText(e.target.value)} placeholder="PKG…, R-012, assoc…" style={{ minWidth: 260 }} />
        <button className="button button--primary" type="submit">
          Search
        </button>
      </form>
      {res.data && res.data.kind === "none" && <p className="muted">No match.</p>}
      {res.data && res.data.kind !== "none" && (
        <div data-testid="search-results">
          <p className="muted">
            {res.data.results.length} {res.data.kind} result(s)
          </p>
          {res.data.results.map((r, i) => (
            <div key={i} className="search-result">
              <table>
                <tbody>
                  {Object.entries(r)
                    .filter(([k]) => k !== "timeline" && k !== "rotation")
                    .map(([k, v]) => (
                      <tr key={k}>
                        <td className="muted" style={{ width: 180 }}>
                          {k.replace(/_/g, " ")}
                        </td>
                        <td>
                          <strong>{v === null || v === undefined ? "—" : String(v)}</strong>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
              {Array.isArray(r.timeline) && (
                <ol className="search-timeline">
                  {(r.timeline as { event: string; clock: string }[]).map((t) => (
                    <li key={t.event}>
                      <span className="tabular">{t.clock}</span> {t.event}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
