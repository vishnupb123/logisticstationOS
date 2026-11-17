# ADR-0014: Fidelity v2 — site profile, canonical statuses, documented metrics and provenance

**Status**: Accepted (2026-11-13). Implements HANDOFF_V2 E1–E5 and E11. Amends ADR-0011 (metric definitions) and ADR-0012 (views). ADR-0008/0009 boundaries are unchanged.

## Context

The owner shared a v2 study set (gitignored `V2/`): 38 screenshots of real station tooling and a definitions sheet. Against them, v1 was directionally right but not credible to a site manager.

**Five headline metrics were computed differently from the station's own definitions:**
- Stow WIP;
- Est. Stow WIP Compliance;
- Induct FPH;
- Lost Hours;
- Induct Downtime DPMO.

**The station day and its objects differed:**
- trailers land the evening before;
- pick starts around 10:00;
- cycles are first-class (standard, high value, unplanned);
- there is an automated sort line with auto-divert fingers;
- linehauls carry containers;
- there is a full package status tree and problem-solve state machines.

## Decision

1. **Metric engine** (`simulation/station_ops/metrics.py`). Each metric declares a label, unit, provenance and formula text, and is computed with its *inputs* exposed (they feed the UI's "How this is calculated" drawer).
   - **Provenance** has three values:
     - `documented`: the owner's sheet, implemented exactly;
     - `observed`: a screen label with inferred semantics;
     - `proposed`: our assumption.
   - **Implemented exactly:**
     - Stow WIP = (INC ÷ Stow FPH) × 60, with a 15/30 min band (Settings);
     - compliance over 15-min intervals;
     - Induct FPH = rolling 10 min × 6;
     - targets = remaining volume ÷ remaining belt run time;
     - belt run time = sort end − sort start − (fast start + breaks + lunch);
     - Lost Hours = belt gaps of 20–120 s;
     - Downtime DPMO = stops ÷ inducted × 10⁶;
     - INC, missed induct, induct dwell (> 60 min), tasks for PSA;
     - pending re-induct (−60/+30 min window);
     - misdivert DPMO and network missorts.
   - v1's `proposed` metrics (DEA, OTD, …) are unchanged and keep their tag.
2. **Settings are data** (`SettingsConfig`):
   - thresholds, compliance interval, FPH window, gap window and dwell are `documented`;
   - fast start, breaks/lunch and the indirect allowance are `proposed`.
   
   Four thresholds are editable live (`PATCH /runtime/sessions/{id}/settings`). The break schedule changes the simulation, so it is set per day.
3. **Site profile timeline** (config defaults):
   - half the road linehauls land on D-1 (−480…−60 min) and wait *in yard*;
   - the dock opens 30 min before the 02:30 sort start;
   - belts stop for breaks;
   - pick starts at 10:00 with waves from 10:50 to 12:10;
   - the final truckfile is published at 15:00.
   
   A `scale` multiplier scales volume, routes and labour together.
4. **Physical model additions:**
   - the **stow buffer**: container fill + transport of 10–24 min, which is why a healthy WIP is 15–30 min;
   - a stow drain of 30 min after pick start;
   - **automated lines** (lines 1..`automated_lines`, with non-conveyables pulled to manual lines);
   - **auto-divert fingers** per cluster with bay capacity (full bay → jackpot);
   - containers (gaylords/pallets) per trip, unloaded container by container;
   - trip legs (facility sequence, ferry leg), operator type and assets;
   - planned vs. unplanned volume, with cycle assignment at induct (dynamic plan);
   - per-package micro-stops (belt-gap defects);
   - missed induct;
   - stower first-sort-attempt failures and spot checks;
   - network missorts.
5. **Problem-solve state machines.**
   - **Damaged:** pending PS → pending approval (a manager work item) → pending stow, or FC return.
   - **Misdivert:** stow-scan-to-PS → pending re-induct → resolved.
   - **Network missort:** pending PS → pending stow → resolved.
6. **Cycle decisions** (new levers):
   - `force_induct`: a bounded window after pick start; late volume goes straight to its route's cart if the van hasn't left;
   - `change_cycle`: rolled-over volume on the floor moves to tomorrow cleanly;
   - `enable_cycle`: the next cycle receives late arrivals.
   
   Without a cycle change, volume inducted after the cut is held as *wrong-cycle induct*.
7. **Canonical status tree** (`status.py`). It is a pure function used by Dwell (by cycle / by delivery window), Ageing (forward / reverse), RTS, and every drill-down list; drill-down endpoint: `GET /runtime/sessions/{id}/packages`. Each package is in exactly one status (tested).

## Consequences

- Baselines moved and were re-measured (see HANDOFF.md §0).
  - Normal-day median Stow WIP compliance over seeds 1–10 is 0.795. Understaffed seeds fall far below, which the agents now detect.
  - The ferry and pitch days are deliberately harder.
- Several semantics remain `observed` or `proposed`: SWA/OTR, "5s", the XPT leg, held sub-reasons, the ≥120 s gap rule and DPMO inclusions (OPEN_QUESTIONS.md, Q4–Q14).
- No real data entered the repo. The study material stays gitignored, and generic names replace every tool, site, and person name.
