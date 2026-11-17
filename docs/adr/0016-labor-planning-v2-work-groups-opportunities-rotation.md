# ADR-0016: Labor planning v2 — work groups, VET/VTO opportunities, rotation

**Status**: Accepted (2026-11-13). Implements HANDOFF_V2 E6–E8. Amends the close-out planning of ADR-0012.

## Context

The station's shift plan reads as:
- per-cycle volume;
- show hours vs. needed hours;
- planned TPH with and without indirect time;
- **work groups** with windows, attendance and expected headcount;
- an **hourly headcount grid by process path**.

VET/VTO run as **opportunities with sign-up windows**: associates *submit* and the station *accepts* up to need. Recommendations are expressed as "post N more for this frame, assuming no more acceptance of submitted ones".

**Rotation** assigns a recommended path per associate from trained paths, disallowed (recently heavy) paths and a rotation priority.

v1 had role counts, offers that associates accepted with a probability (inverted semantics), and a ≤2-consecutive-days rule.

## Decision

1. **`labor_plan.py`.** It derives flows per hour from the linehaul plan and the documented belt-run-time rule:
   - receive, auto/manual induct, non-con, stow, pick, HV, RTS, fixed lines and yard.
   
   From the flows it computes `needed[path][hour] = flow ÷ rate (+ fixed)` over 15 generic process paths in five labour groups (rates `proposed`). Work groups are then sized as follows:
   - groups with a given roster (the managed crew) come first;
   - every other group covers the residual need in its window, using fractional hour overlap.
   
   The output covers the cycle table, totals (show/needed hours, TPH with and without the indirect allowance), the work-group table and the hourly grid.
2. **`opportunities.py`.**
   - **Posting:** `post(type, HC, frame)` opens a sign-up window (default 180 min, closing at least 60 min before the frame).
   - **Submission:** eligible associates submit with probability `base × max(0.25, min(1, lead_h / 12))`, which is `proposed`.
   - **Acceptance:** first come, or rotation-aware at window close. VTO prefers associates carrying the heaviest load.
   - **Recommendations:** `max(0, need − accepted)` per frame.
   - **Compatibility:** v1's `offer_vet/offer_vto` levers map to `post_opportunity`, and `Closeout.offers` remains as a per-submission view.
3. **`rotation.py`.** A Hungarian min-cost assignment (scipy when installed, greedy fallback) of available associates to path slots taken from the plan's sort-phase peak plus HV and dedicated pickers. The cost model is `−skill + 1.0 if same path as yesterday − 0.6 for rotating a High-priority associate off heavy work`, and untrained or disallowed paths cost ∞. Two rules apply:
   - **Disallowed:** a heavy path on ≥2 of the last 3 days (`proposed`, Q10).
   - **Compliance:** no path for more than `max_consecutive_same_role` days in a row.
4. **Agents:** the Shift Planning agent posts opportunities from the recommendations (reflex), flags windows closing short, and re-runs rotation when it is non-compliant.

## Consequences

- The plan's show-vs-needed shape now mirrors the station's own plan.
- Every rate and behaviour is proposed until the owner answers Q5, Q9 and Q10.
- Per-associate data stays synthetic.
