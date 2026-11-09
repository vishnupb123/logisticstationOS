// Generic enterprise table: sortable headers, optional per-column text
// filters (like the station tooling's filter row), sticky header, scroll.
import { type ReactNode, useMemo, useState } from "react";
import "./DataTable.css";

export interface Column<T> {
  key: string;
  label: string;
  num?: boolean;
  render?: (row: T) => ReactNode;
  value?: (row: T) => string | number | null | undefined;
  filter?: boolean;
  width?: number;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  maxHeight = 520,
  empty = "Nothing to show.",
  rowClass,
  testId,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  maxHeight?: number;
  empty?: string;
  rowClass?: (row: T) => string | undefined;
  testId?: string;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const hasFilters = columns.some((c) => c.filter);

  const val = (c: Column<T>, r: T) =>
    c.value ? c.value(r) : ((r as Record<string, unknown>)[c.key] as string | number | null | undefined);

  const shown = useMemo(() => {
    let out = rows.filter((r) =>
      columns.every((c) => {
        const f = filters[c.key];
        if (!f) return true;
        return String(val(c, r) ?? "").toLowerCase().includes(f.toLowerCase());
      }),
    );
    if (sort) {
      const c = columns.find((x) => x.key === sort.key);
      if (c) {
        out = [...out].sort((a, b) => {
          const va = val(c, a);
          const vb = val(c, b);
          if (va === vb) return 0;
          if (va === null || va === undefined) return 1;
          if (vb === null || vb === undefined) return -1;
          return (va > vb ? 1 : -1) * sort.dir;
        });
      }
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, filters, sort, columns]);

  return (
    <div className="dt" style={{ maxHeight }} data-testid={testId}>
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className={c.num ? "num" : undefined}
                style={c.width ? { width: c.width } : undefined}
                onClick={() =>
                  setSort((s) => (s?.key === c.key ? { key: c.key, dir: s.dir === 1 ? -1 : 1 } : { key: c.key, dir: 1 }))
                }
                aria-sort={sort?.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
              >
                {c.label}
                <span className="dt__sort">{sort?.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : "↕"}</span>
              </th>
            ))}
          </tr>
          {hasFilters && (
            <tr className="dt__filters">
              {columns.map((c) => (
                <th key={c.key}>
                  {c.filter && (
                    <input
                      aria-label={`Filter ${c.label}`}
                      value={filters[c.key] ?? ""}
                      onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                    />
                  )}
                </th>
              ))}
            </tr>
          )}
        </thead>
        <tbody>
          {shown.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="muted">
                {empty}
              </td>
            </tr>
          ) : (
            shown.map((r) => (
              <tr key={rowKey(r)} className={rowClass?.(r)}>
                {columns.map((c) => (
                  <td key={c.key} className={c.num ? "num tabular" : undefined}>
                    {c.render ? c.render(r) : (val(c, r) ?? "—")}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
      <div className="dt__count">
        {shown.length} of {rows.length}
      </div>
    </div>
  );
}
