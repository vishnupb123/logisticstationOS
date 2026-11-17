// Unified work-item inbox (HANDOFF_V2 E10): one filterable list for every
// task the simulated station raises — notifications, close-out tasks, agent
// recommendations, scrubs and reviews — with an expiring-in countdown against
// the simulated clock. Agent recommendations are approved / dismissed here
// (the human-approval gate); everything else is completed / dismissed.
import { useMemo, useState } from "react";
import { useStation } from "../api/runtime";
import { type WorkItem, useWorkItem } from "../api/runtimeV2";
import { type Column, DataTable } from "./DataTable";
import { DataUpdated } from "./MetricDrawer";
import "./WorkItemInbox.css";

const WORK_CATEGORIES = ["Induct", "Sort", "Pick & Stage", "Dispatch", "Fleet", "Safety", "Ops Updates", "People"] as const;
const STATES = ["pending", "done", "expired", "dismissed"] as const;
const PRIORITY: Record<number, { label: string; tone: string; icon: string }> = {
  1: { label: "High", tone: "bad", icon: "!" },
  2: { label: "Medium", tone: "warn", icon: "▲" },
  3: { label: "Low", tone: "neutral", icon: "·" },
};
const STATE_TONE: Record<string, string> = { pending: "info", done: "good", expired: "bad", dismissed: "neutral" };

function countdown(mins: number): string {
  if (mins <= 0) return "due now";
  const m = Math.ceil(mins);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

function Actions({ w }: { w: WorkItem }) {
  const m = useWorkItem();
  if (w.state !== "pending") {
    return <span className="muted wi__closed">{w.closed_clock ? `closed ${w.closed_clock}` : "—"}</span>;
  }
  const isRec = w.recommendation_id !== undefined && w.recommendation_id !== null;
  return (
    <span className="wi__actions">
      <button
        className="button button--sm button--primary"
        disabled={m.isPending}
        onClick={() => m.mutate({ id: w.id, verb: "complete" })}
        data-testid={`wi-complete-${w.id}`}
      >
        {isRec ? "Approve" : "Complete"}
      </button>
      <button
        className="button button--sm"
        disabled={m.isPending}
        onClick={() => m.mutate({ id: w.id, verb: "dismiss" })}
        data-testid={`wi-dismiss-${w.id}`}
      >
        Dismiss
      </button>
      {m.error && <span className="wi__err">{String(m.error.message)}</span>}
    </span>
  );
}

export function WorkItemInbox({
  items,
  initialState = "pending",
  initialCategory = "all",
  maxHeight = 560,
}: {
  items: WorkItem[];
  initialState?: string;
  initialCategory?: string;
  maxHeight?: number;
}) {
  const q = useStation();
  const now = q.data?.snapshot.minute ?? 0;
  const [category, setCategory] = useState(initialCategory);
  const [state, setState] = useState(initialState);
  const [priority, setPriority] = useState("all");

  const rows = useMemo(
    () =>
      items
        .filter((w) => category === "all" || w.category === category)
        .filter((w) => state === "all" || w.state === state)
        .filter((w) => priority === "all" || String(w.priority) === priority)
        .sort((a, b) => a.priority - b.priority || a.expires_at - b.expires_at),
    [items, category, state, priority],
  );

  const columns: Column<WorkItem>[] = [
    {
      key: "priority",
      label: "Priority",
      value: (w) => w.priority,
      render: (w) => {
        const p = PRIORITY[w.priority] ?? PRIORITY[3];
        return (
          <span className={`pill pill--${p.tone}`}>
            <span aria-hidden>{p.icon}</span> {p.label}
          </span>
        );
      },
    },
    {
      key: "title",
      label: "Task",
      render: (w) => (
        <span className="wi__title">
          {w.title}
          {w.carried && <span className="wi__tag">carried over</span>}
          {w.recommendation_id != null && <span className="wi__tag">agent recommendation</span>}
        </span>
      ),
      filter: true,
    },
    { key: "process", label: "Process" },
    { key: "kind", label: "Type", value: (w) => w.kind.replace(/_/g, " ") },
    { key: "associate", label: "Associate", value: (w) => w.associate ?? "—" },
    { key: "owner", label: "Owner" },
    { key: "started_by", label: "Started by" },
    { key: "created", label: "Created", value: (w) => w.created, render: (w) => <span className="tabular">{w.created_clock}</span> },
    {
      key: "expires",
      label: "Expiring in",
      value: (w) => w.expires_at,
      render: (w) =>
        w.state === "pending" ? (
          <span className={`tabular${w.expires_at - now <= 15 ? " wi__soon" : ""}`} title={`expires ${w.expires_clock}`}>
            {countdown(w.expires_at - now)}
          </span>
        ) : (
          <span className="muted tabular">{w.state === "expired" ? `expired ${w.expires_clock}` : "—"}</span>
        ),
    },
    {
      key: "state",
      label: "State",
      render: (w) => <span className={`pill pill--${STATE_TONE[w.state] ?? "neutral"}`}>{w.state}</span>,
    },
    { key: "actions", label: "Action", render: (w) => <Actions w={w} /> },
  ];

  return (
    <div className="wi" data-testid="work-item-inbox">
      <div className="wi__filters">
        <label>
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Filter by category">
            <option value="all">All categories</option>
            {WORK_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          State
          <select value={state} onChange={(e) => setState(e.target.value)} aria-label="Filter by state">
            <option value="all">All states</option>
            {STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Priority
          <select value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Filter by priority">
            <option value="all">All priorities</option>
            {[1, 2, 3].map((p) => (
              <option key={p} value={String(p)}>
                {PRIORITY[p].label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <DataTable
        testId="work-items-table"
        columns={columns}
        rows={rows}
        rowKey={(w) => w.id}
        maxHeight={maxHeight}
        empty={state === "pending" ? "No pending work items — new ones appear as the simulated shift raises them." : "No work items match these filters."}
      />
      <DataUpdated />
    </div>
  );
}
