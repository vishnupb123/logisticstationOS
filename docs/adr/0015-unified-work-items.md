# ADR-0015: Unified work items

**Status**: Accepted (2026-11-13). Implements HANDOFF_V2 E10.

## Context

v1 had three parallel "someone must act" surfaces:
- notifications (bell + acknowledge);
- close-out tasks (supervisor/manager queues);
- agent recommendations (approve/dismiss).

The station runs on one surface: **work items**. Each has a category, priority/severity, an owner, who started it, an expiry, and states such as Completed Today, Expired Today and carry-over from previous days.

## Decision

- **Store.** `simulation/station_ops/work_items.py` (`WorkItemStore` on the twin). A work item has:
  - `category`: Induct, Sort, Pick & Stage, Dispatch, Fleet, Safety, Ops Updates or People;
  - `process`, `priority` (1–3), `owner`, `associate`, `started_by` (system/agent/person) and `ref`;
  - `created` and `expires_at` (a per-kind SLA, `proposed`);
  - `state`: pending, done, expired or dismissed;
  - `resolution`;
  - `carried`.
- **Sources:**
  - every supervisor/manager notification that is warning/critical or of a mapped kind;
  - every close-out task (closed when the task finishes);
  - damaged-package approvals;
  - and, in the runtime state, every pending agent recommendation (`REC-<id>`, completing = approve).
- **Auto-resolution.** An item closes when the underlying condition is fixed: a cart is restaged, a van is replaced, the sweep or a cluster transfer recovers a bag, or a cycle is changed.
- **Expiry.** Items expire deterministically on the sim clock (a 5-minute sampler tick). Open items carry over into the next day's config (`carried_work_items`).
- **API:** `POST /runtime/sessions/{id}/work-items/{id}/{complete|dismiss}`. The bell shows the pending count, and `/work-items` is the inbox.

## Consequences

- Expired items are now visible and countable. The assistant answers "what expired today?".
- SLA minutes and the category mapping are proposed.
- Notifications are kept for history and DSP/driver messages; acknowledging a notification's work item also acks the notification.
