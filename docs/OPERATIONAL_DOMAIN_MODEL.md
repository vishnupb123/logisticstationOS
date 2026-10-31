# Operational Domain Model

> **Synthetic domain notice**: this document describes a fictional reference station, "**Station NOVA-1**," used purely to give StationOS a concrete, generic parcel-logistics process to model. All counts, identifiers, aisle layouts, and timings are configurable synthetic defaults for engineering and simulation purposes — not a verified replica of any real facility's current proprietary operation. Where a formula or threshold is organization-specific and unknown to this project, it is marked `requires_validation` rather than invented.

## 1. Process overview

Station NOVA-1 runs two operating cycles per day:

- **Cycle 1 — Overnight Induct** (~02:30 start): inbound trucks → induct → classification → sortation → stow.
- **Cycle 2 — Pick & Stage and Dispatch** (post-induct): pick → cart staging → wave-based dispatch → yard departure.
- **Post-dispatch / Planning**: reconciliation, returns processing, forecasting, next-cycle planning.

All clock times below (e.g., "02:30", "Wave 1 at 11:10") are **synthetic defaults for the reference scenario**, implemented as configuration, not hardcoded universal rules — a different station profile should be able to override every one of them.

## 2. Entities

| Entity | Description |
|---|---|
| Truck | Inbound vehicle carrying pallets from an origin location |
| Pallet | Unit load of parcels arriving on a truck |
| Parcel | Individually tracked unit; carries an original label (tracking ID + origin) |
| SAL label | Station-applied label printed and attached during induct, distinct from the original tracking label |
| Induct belt | Conveyance where crashers feed parcels for scanning/classification |
| Classification outcome | Normal Cycle-1 / Sideline / High-value / Future-date / Exception |
| Sort cluster | Cluster A (aisles A1–A54) or Cluster B (aisles B1–B68) — 122 aisles total in the reference configuration |
| Aisle | Has one hamper and one scanner |
| Hamper | Receptacle a sort-cluster diverts parcels into; has finite capacity |
| Jackpot | Catch-all for failed/incorrect scans or full-hamper diversions; must be cleared and reintroduced |
| Stower | Associate who moves parcels from hampers into bags via a stow trolley |
| Bag | Container of stowed parcels, the unit carried into Pick & Stage |
| High-value cage (Atlas-style) | Separate exception workflow for high-value parcels: collect → repack if needed → verify against high-value list → confirm received → confirm inducted → confirm virtual stow |
| Cart | Route-coded container associates fill during Pick & Stage |
| Route | A delivery route code; determines cart/bag assignment |
| Wave | A scheduled staging/dispatch batch; the reference default is Wave 1 at 11:10 with subsequent waves at 20-minute intervals — configurable, not universal |
| Staging location | Where a completed cart is placed awaiting dispatch |
| Van | Vehicle assigned to a route for dispatch |
| Yard | Function coordinating van/route departures |
| Return | A parcel or cart that comes back into the station (driver return, FC return) |

## 3. Process flow

### 3.1 Cycle 1 — Overnight Induct

1. Trucks arrive from origin locations with pallets of parcels.
2. Crashers feed parcels onto the induct belt.
3. A camera scans the original label; a SAL label is printed and attached.
4. A scanner classifies the parcel: Normal Cycle-1, Sideline, High-value, Future-date, or Exception.
5. Exception parcels divert to problem-solve areas; eligible parcels proceed to sortation.
6. Each sort cluster (A or B) scans and diverts parcels to the assigned aisle's hamper; failed/incorrect scans divert to jackpot.
7. Stowers collect parcels from hampers and stow them into bags.
8. Full hampers divert overflow to jackpot; jackpot must be cleared and reintroduced into the process.
9. At end of induct, supervisors may need to reconcile physical parcels against virtual stow records (locate parcels believed stowed but not confirmed, or vice versa).

High-value parcels bypass steps 6–8 and run through the separate cage workflow described in §2.

**Supervisor monitoring surface** (induct): induct flow rate, sortation performance, stow capacity, work-in-process (WIPS), jackpot accumulation, aisle/hamper availability, process imbalance between clusters, parcel dwell time, exception volume.

### 3.2 Cycle 2 — Pick & Stage and Dispatch

1. Associates collect parcels and place them into carts by delivery route code.
2. Carts are staged at designated locations per the wave plan.
3. Dispatch proceeds in waves (reference default: Wave 1 at 11:10, +20 min thereafter — configurable).
4. The yard function coordinates vans and route departures, tracking on-time vs. late-departure risk.

**Supervisor monitoring surface** (Pick & Stage): route assignment, cart allocation, picking progress, staging completion, wave readiness, resource availability, route exceptions.

**Other modeled exceptions**: UK parcel processing, FC-return processing, missing route carts, late drivers, unpicked routes, incomplete staging, driver returns.

### 3.3 Post-dispatch and Planning

Truck-schedule updates, inbound-volume forecasting (incorporating origin/ferry information), capacity evaluation, staffing-requirement planning, VET/VTO scenario evaluation (as a **planning concept only** — never an autonomous workforce action), returned-parcel processing, station housekeeping/readiness.

## 4. Metric contract framework

Every operational metric in StationOS must carry this contract before it is implemented. Status is one of `proposed` (contract drafted, not yet validated against real definitions), `validated` (confirmed correct and signed off), or `deprecated`.

```
Metric: <name>
Description: <plain-language definition>
Unit: <%, count, minutes, ...>
Numerator / Denominator: <if a ratio>
Calculation logic: <formula, or "requires_validation">
Required source events: <event types needed>
Time window: <e.g., per cycle, rolling 1h>
Data-quality requirements: <completeness/latency assumptions>
Version: <contract version>
Known limitations: <caveats>
Status: proposed | validated | deprecated
```

### 4.1 Initial metric catalog

The exact calculation for organization-specific metrics (DEA, OTD, Sort Compliance, FPY, FSAF, WIPS) is **not known to this project** and must not be invented. Each is listed below with a generic description only; numerator/denominator/formula is `requires_validation` until confirmed by a domain owner.

| Metric | Description (generic) | Status |
|---|---|---|
| DEA (Delivery Estimate Accuracy) | How closely actual delivery timing matches an estimate given to a customer | `requires_validation` — formula unknown |
| OTD (On-Time Departure) | Whether a route/van departs the station within its planned window | `requires_validation` — exact window/tolerance unknown |
| Sort Compliance | Degree to which parcels are sorted to their correct aisle/hamper on first attempt | `requires_validation` — formula unknown |
| Timely Staged | Whether a cart/route reaches its staging location in time for its wave | `requires_validation` — exact threshold unknown |
| FPY (First Pass Yield) | Proportion of parcels that complete a process step correctly without rework | `requires_validation` — formula unknown |
| FSAF (First Scan at Facility) | Time/compliance of a parcel's first scan event at the station | `requires_validation` — formula unknown |
| WIPS (Work in Process) | Count of parcels currently between induct and confirmed stow/dispatch | `proposed` — defined here as `count(parcels where state in {inducted, sorted, in_hamper} and not confirmed_stowed)`; still needs validation against real operational usage |
| Induct throughput | Parcels inducted per unit time | `proposed` — `count(induct events) / time_window`, generic enough to define directly |
| Jackpot volume | Count of parcels currently or cumulatively diverted to jackpot | `proposed` — `count(jackpot_divert events) [- count(jackpot_clear events)]` for current volume |
| Parcel dwell time | Elapsed time a parcel spends between two lifecycle events (e.g., induct → stow) | `proposed` — `event_B.timestamp - event_A.timestamp`, generic definition |
| Stow throughput | Parcels stowed per unit time per stower or per station | `proposed` — `count(stow events) / time_window` |
| Route readiness | Whether a route's cart(s) are staged and complete ahead of its wave | `requires_validation` — exact completeness criteria unknown |

Metrics marked `proposed` here are generic enough to define without organizational knowledge but still require sign-off before being treated as validated. Metrics marked `requires_validation` must not be computed and surfaced as if authoritative until a domain owner confirms the formula — see `docs/OPEN_QUESTIONS.md`.

## 5. Confirmed vs. assumption vs. open

- **Confirmed** (given directly as the domain spec for this project): entities, process flow, exception types, supervisor monitoring surfaces, metric names.
- **Assumption** (reasonable default, not confirmed): exact clock times, 122-aisle split, wave cadence — all implemented as configuration, not fact.
- **Open / requires validation**: every metric's exact formula; see §4.1 and `docs/OPEN_QUESTIONS.md`.
