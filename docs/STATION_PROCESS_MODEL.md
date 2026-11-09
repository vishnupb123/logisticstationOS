# Station process model — what was learned, and where it lives

The project owner shared screenshots of real station command tooling (kept locally in `images/`, gitignored and never committed, because they contain real logins and identifiers). This document records the **generic process concepts** learned from them and the StationOS feature that implements each one. No names, identifiers, data or visual branding were copied. Every metric definition is `proposed` (docs/OPERATIONAL_DOMAIN_MODEL.md §4.1).

## Process flow

```
linehaul (road / ferry) → yard → dock door (unload sequence) → receive
  → induct line (scan: clean / no-read / multi-read / misapplied label / damaged → problem solve)
  → high-value? → custody scan-in → HV cage ──────────────┐
  → sort → stow into aisle bay (full bay → jackpot → clear) │
  → CYCLE pick start: induct blocked, un-stowed volume rolls over; stowers/inductors convert to pickers
  → picklist (priority, sideline) → carts → staging location ← HV custody handoff
  → DSP driver check-in (swipe) → load → depart (OTD) → stop-by-stop delivery attempts (DEA)
  → return to station (RTS) → swipe to finish
```

## Concept → feature map

| Learned concept | StationOS feature | Where |
|---|---|---|
| Cycle alert: pick started, so induct is blocked | Global cycle banner; rollover at pick start | `/` shell, model `_cycle_process` |
| Station performance summary: induct FPH, lost hours, induct downtime DPMO, quality (no-read, multi-read, misapplied label), each with its top 3 impacted lines | Command Center performance cards | `/command`, `views.performance` |
| Stow metrics: stow FPH/PPH, est. stow WIP compliance, stow WIP band | Command Center and Sort Overview KPIs | `/command`, `/induct` |
| Dwell by cycle (No cycle / CYCLE_1 / High_Value) and by scheduled delivery window | Package Summary → Dwell | `/packages`, `views.dwell` |
| Ageing (<1, 1, 2, 3, 4+ days) by status, in-station and on-road scrubs, review of missing and lost packages | Package Summary → Ageing | `/packages?tab=ageing` |
| RTS: inbound, at station, delivery cancelled, by type | Package Summary → RTS | `/packages?tab=rts` |
| Search by package, container or associate | Global search and the Search tab | top bar, `/packages?tab=search` |
| Receive overall status: predicted dispatch, planned vs unplanned, manifested vs unplanned-manifested, in transit, reprocess | Receive → Overall status | `/inbound` |
| Linehauls: trip, origin, yard/in transit, door, planned/actual, volume, unload sequence, with group-by | Receive → Linehauls (unload-first action) | `/inbound` |
| Sort overview: sortation-flow chart with series toggles; 15 min / 30 min / 1 hour / cumulative actuals for receive, induct, stow, TPH and labour | Sort Overview | `/induct` |
| Stow buffer: full bays, jackpot rate, no-read rate, current volume, % of station volume, avg PPH | Stow & Buffers | `/stow` |
| Pick: route view and layout grid view, SPR thresholds and high-SPR flag, picklist states, prioritise / sideline / unassign, average duration | Pick | `/pick` |
| Stage: timely staged %, not ready / ready / partially staged / staged, staging location, carts | Stage | `/stage` |
| Outbound overview: wave grid with at risk, partial and stalled states; visual and table views | Outbound Overview | `/outbound` |
| Depart, with DSPs and drivers | Dispatch & DSP coordination: notify, reroute by sector, move to the next wave, standby, swipe reminders, live map | `/dispatch` |
| High-value handling | High-Value Processing: custody scans, cage dwell, reinforcement | `/high-value` |
| Associates by function: picklist assigned, time since last activity, idle time between picklists, last location | Associates | `/associates` |
| Shift plan: OFD date, total/planned volume, sideline/RTS, planned rollover, show vs needed hours, planned TPH, work groups with attendance, VET/VTO | Shift Plan (recomputed live); shift rotation | `/labor` |
| Station layout, sort paths (cycle partitions and grid overlaps), devices | Station & Resources | `/station` |
| Work items, problem solve | Work Items (one-click actions); Problem Solve | `/work-items`, `/problem-solve` |

## Beyond what the screenshots show

- Five specialist agents with robust counterfactual planning over belief futures, labor arbitration, a situation-conditioned playbook, and online capacity learning. See ADR-0012.
- A Station Assistant chat that answers from live state and gets agents to act ("fix stow WIP"), plus what-if and drill commands.
- Ferry ETAs that are revealed progressively (truckfile refresh), and seeded daily friction, so no two days are alike.
