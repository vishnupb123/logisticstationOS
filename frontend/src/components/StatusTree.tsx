// The generic package status tree (HANDOFF_V2 E4/E11): expandable group rows
// → sub-status rows × columns. Every drillable count is a button that opens
// a drawer listing the packages behind it (GET /packages), whose length
// equals the count. Also exports the side Drawer used by other v2 pages.
import { Fragment, type ReactNode, useEffect, useRef, useState } from "react";
import { type PackageListItem, usePackages } from "../api/runtimeV2";
import { type Column, DataTable } from "./DataTable";
import { DataUpdated } from "./DataUpdated";
import { ErrorState, LoadingState } from "./QueryStates";
import "./StatusTree.css";

export function Drawer({
  title,
  onClose,
  children,
  testId,
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  testId?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    // focus once on open (live data re-renders every second; don't steal focus)
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="v2-drawer__scrim" onClick={onClose}>
      <div
        ref={ref}
        className="v2-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        tabIndex={-1}
        data-testid={testId}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="v2-drawer__head">
          <h2>{title}</h2>
          <button className="button button--sm" onClick={onClose} aria-label="Close">
            Close
          </button>
        </header>
        <div className="v2-drawer__body">{children}</div>
      </div>
    </div>
  );
}

export interface TreeRow {
  status: string;
  [column: string]: unknown;
}
export interface TreeGroup {
  group: string;
  rows: TreeRow[];
  [column: string]: unknown;
}
export interface DrillParams {
  group: string;
  status?: string;
  column?: string;
  by?: "cycle" | "window";
}

const num = (v: unknown) => (typeof v === "number" ? v : Number(v ?? 0) || 0);
const LIST_CAP = 500;

const PKG_COLS: Column<PackageListItem>[] = [
  { key: "tracking_id", label: "Tracking ID", filter: true },
  { key: "status", label: "Status", filter: true },
  { key: "cycle", label: "Cycle", filter: true },
  { key: "route", label: "Route", filter: true },
  { key: "container", label: "Container", value: (p) => p.container ?? "—" },
  { key: "planned", label: "Planned", value: (p) => (p.planned ? "Planned" : "Unplanned") },
  { key: "location", label: "Location", value: (p) => p.location ?? "—" },
];

export function PackageListDrawer({ params, onClose }: { params: DrillParams; onClose: () => void }) {
  const q = usePackages(params);
  const title = [params.group, params.status, params.column].filter(Boolean).join(" · ");
  return (
    <Drawer title={title} onClose={onClose} testId="package-list">
      {q.isLoading && <LoadingState />}
      {q.error && <ErrorState error={q.error} />}
      {q.data && (
        <>
          <p>
            <strong data-testid="package-list-count">
              {q.data.count.toLocaleString()} package{q.data.count === 1 ? "" : "s"}
            </strong>
            {q.data.count > LIST_CAP && <span className="muted"> · showing the first {LIST_CAP}</span>}
          </p>
          <DataTable
            columns={PKG_COLS}
            rows={q.data.items.slice(0, LIST_CAP)}
            rowKey={(p) => p.tracking_id}
            maxHeight={560}
            empty="No packages in this status right now."
          />
        </>
      )}
    </Drawer>
  );
}

export function StatusTree({
  columns,
  columnLabels,
  groups,
  totalKey,
  drill,
  clock,
  testId,
  firstHeader = "Status",
}: {
  columns: string[];
  columnLabels?: Record<string, string>;
  groups: TreeGroup[];
  /** Field holding each row's total; when absent the total is the sum of `columns`. */
  totalKey?: string;
  /** Returns the package-list query for a count, or null when it is not drillable. `column` is undefined for the total. */
  drill?: (group: string, status: string | undefined, column: string | undefined) => DrillParams | null;
  clock?: string;
  testId?: string;
  firstHeader?: string;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [sel, setSel] = useState<DrillParams | null>(null);
  const total = (r: Record<string, unknown>) => (totalKey ? num(r[totalKey]) : columns.reduce((a, c) => a + num(r[c]), 0));

  const cell = (group: string, status: string | undefined, column: string | undefined, value: number) => {
    const p = value > 0 ? drill?.(group, status, column) : null;
    const label = `${group}${status ? ` · ${status}` : ""}${column ? ` · ${columnLabels?.[column] ?? column}` : " · total"}`;
    return p ? (
      <button className="count-link tabular" onClick={() => setSel(p)} aria-label={`${value} packages: ${label}`}>
        {value.toLocaleString()}
      </button>
    ) : (
      <span className="tabular">{value.toLocaleString()}</span>
    );
  };

  return (
    <div>
      <div className="table-scroll st-wrap">
        <table className="status-tree" data-testid={testId}>
          <thead>
            <tr>
              <th>{firstHeader}</th>
              {columns.map((c) => (
                <th key={c} className="num">
                  {columnLabels?.[c] ?? c}
                </th>
              ))}
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const isOpen = !!open[g.group];
              return (
                <Fragment key={g.group}>
                  <tr className="status-tree__group">
                    <td>
                      <button
                        className="status-tree__toggle"
                        aria-expanded={isOpen}
                        onClick={() => setOpen((o) => ({ ...o, [g.group]: !isOpen }))}
                        disabled={g.rows.length === 0}
                      >
                        <span aria-hidden>{g.rows.length === 0 ? "·" : isOpen ? "▾" : "▸"}</span> {g.group}
                      </button>
                    </td>
                    {columns.map((c) => (
                      <td key={c} className="num">
                        {cell(g.group, undefined, c, num(g[c]))}
                      </td>
                    ))}
                    <td className="num">{cell(g.group, undefined, undefined, total(g))}</td>
                  </tr>
                  {isOpen &&
                    g.rows.map((r) => (
                      <tr key={r.status} className="status-tree__row">
                        <td>{r.status}</td>
                        {columns.map((c) => (
                          <td key={c} className="num">
                            {cell(g.group, r.status, c, num(r[c]))}
                          </td>
                        ))}
                        <td className="num">{cell(g.group, r.status, undefined, total(r))}</td>
                      </tr>
                    ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {clock !== undefined && <DataUpdated clock={clock} />}
      {sel && <PackageListDrawer params={sel} onClose={() => setSel(null)} />}
    </div>
  );
}
