# Station process model — what was learned, and where it lives

The project owner shared screenshots of real station command tooling (kept locally in `images/`, gitignored and never committed, because they contain real logins and identifiers). This document records the **generic process concepts** learned from them and the StationOS feature that implements each one. No names, identifiers, data or visual branding were copied. Every metric definition is `proposed` (docs/OPERATIONAL_DOMAIN_MODEL.md §4.1).

## v2 (2026-11-13): what the second study added

A second, ordered study (gitignored `V2/`: 38 screenshots plus the owner's definitions sheet) changed the model. The full write-up is in `HANDOFF_V2.md` §2–§4; ADR-0014/0015/0016 cover the decisions. In brief:

- **Timeline and receive:**
  - trailers land the evening before and wait in the yard, with an unload sequence;
  - sort starts at 02:30 with breaks; pick starts at 10:00 (waves 10:50–12:10);
  - linehauls carry gaylords/pallets and have multi-leg facility sequences (ferry legs);
  - volume is planned or unplanned.
- **Sort:**
  - an automated line (auto-scan loader → labeler → pushers → auto-divert fingers → container building) runs beside manual lines; non-conveyables go manual;
  - a stow buffer of 10–24 min makes a healthy stow WIP 15–30 min.
- **Metrics:** the five headline metrics now follow the owner's documented definitions (Stow WIP, 15-min compliance, Induct FPH, belt-gap lost hours, downtime DPMO), and provenance is shown on every metric.
- **Cycles:** pick start blocks induct, and late volume is handled by force induct, change cycle or enable cycle; otherwise it is held as wrong-cycle.
- **Package status and problem solve:** one canonical status tree, plus problem-solve state machines (damaged with manager approval, misdivert re-induct, network missorts).
- **Planning:**
  - labor plan v2 has work groups and an hourly path-headcount grid;
  - VET/VTO are opportunities with sign-up windows (associates submit, the station accepts);
  - rotation uses trained and disallowed paths.
- **Exceptions:** work items (category, owner, expiry, carry-over) unify notifications, close-out tasks and agent recommendations.

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
  → [after the last departure] associates off shift (sweepers finish first)
  → supervisor: GTDRs (late inbound / outbound pallet trucks), ferry checks,
    final truckfile (revisions keep coming), in-station & on-road scrubs
  → manager: OFD volume, SPR, TPH, needed vs expected headcount → VET/VTO
    offers (associates choose) → tomorrow's plan (aisle volume, stow zones,
    task assignment with job rotation) → end-of-shift review / re-plan
```

Floor and yard exceptions along the way: a cart scanned into the wrong staging location (supervisor and both DSPs notified; the route can't load until it is restaged), a bag picked but not scanned to a cart (flagged at staging; the sweeper re-stages it if the van hasn't left, otherwise it becomes a cluster transfer for the next cycle), uncaught missorts found by the sweep or the scrub, and the yard marshal's vehicle safety audit (VSA) — minor defects fixed on site, critical ones ground the van until a spare, borrowed or rental van arrives.

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
| GTDR = Global Trailer Dock and Release (owner, 2026-11-12) | Close-out → GTDR tab | `/closeout` |
| The final truckfile drives the next cycle | "Run day N+1 from truckfile vN" (also in the session bar) | `/closeout`, `closeout.next_day_config` |
| After-dispatch close-out (from the project owner's description): GTDR, ferry checks / truckfile updates that continue after the final, in-station and on-road scrubs, headcount → VET/VTO, daily plan with aisle volume division and job rotation | Close-out & Tomorrow (supervisor and manager task queues, tomorrow's truckfile with revisions, GTDR, offers, plan, readiness) | `/closeout`, `closeout.py` |
| Wrong staging scan → notify supervisor, manage neighbouring routes, tell DSPs/drivers | Staging floor plan (live), notification centre, DSP comms; `restage_cart` | `/stage`, bell, `/dispatch` |
| Sweep of picked aisles; left-behind parcels staged to the cart or cluster-transferred | Aisle plan (live), sweep log; `direct_sweep` | `/pick` → Aisle plan, `/closeout` |
| Yard marshal VSA, grounded vans and follow-up | Dispatch → Yard · VSA; `request_replacement_van`, `add_yard_marshal` | `/dispatch` |
| Realistic driver map | Road network with river and bridges; drivers drive along roads; selected driver's path and stops | `/dispatch`, `geo.py` |

## Beyond what the screenshots show

- Five specialist agents with robust counterfactual planning over belief futures, labor arbitration, a situation-conditioned playbook, and online capacity learning. See ADR-0012.
- A Station Assistant chat that answers from live state and gets agents to act ("fix stow WIP"), plus what-if and drill commands.
- Ferry ETAs that are revealed progressively (truckfile refresh), and seeded daily friction, so no two days are alike.
