"""Synthetic linehaul plans and the shipped Station Operations presets.

Pure functions, seeded: the truckfile service (app/inbound/) uses
`generate_linehaul_plan` to create the day's synthetic truckfile, and
the presets below build twin configs without any database at all.
Every origin/trip/sailing code is synthetic — no real network names.
"""

import random
from datetime import date

from app.core.determinism import rng_hex
from app.simulation.station_ops.config import (
    Disruption,
    FerryRevision,
    LinehaulPlan,
    StationOpsConfig,
)

ROAD_ORIGINS = ("HUB-N1", "HUB-N2", "HUB-E1", "XDOCK-W1")
FERRY_ORIGINS = ("PORT-X1", "PORT-X2")
#: Synthetic ferry crossings: origin port -> sailing departure minutes
#: (relative to OFD-date midnight; negative = previous evening).
FERRY_SAILINGS = {
    "PORT-X1": (-150, 30, 150),
    "PORT-X2": (-60, 90),
}
FERRY_CROSSING_MINUTES = 200


def generate_linehaul_plan(
    seed: int, ofd_date: date, *, total_volume: int = 12000, ferry_share: float = 0.3
) -> list[LinehaulPlan]:
    rng = random.Random(f"linehaul-plan:{seed}:{ofd_date.isoformat()}")
    trips: list[LinehaulPlan] = []

    ferry_volume = int(total_volume * ferry_share)
    ferry_slots = [(o, s) for o, sailings in FERRY_SAILINGS.items() for s in sailings]
    per_ferry = ferry_volume // len(ferry_slots)
    for origin, sailing_minute in ferry_slots:
        trips.append(
            LinehaulPlan(
                trip_id=f"LH-{rng_hex(rng, 3)}",
                origin=origin,
                planned_arrival_minute=sailing_minute + FERRY_CROSSING_MINUTES + 25,
                volume=per_ferry + rng.randint(-40, 40),
                via_ferry=True,
                ferry_sailing=f"SAIL-{origin[-2:]}-{(sailing_minute % 1440) // 60:02d}"
                f"{(sailing_minute % 1440) % 60:02d}",
            )
        )

    road_volume = total_volume - sum(t.volume for t in trips)
    road_count = 10
    per_road = road_volume // road_count
    for i in range(road_count):
        volume = per_road if i < road_count - 1 else road_volume - per_road * (road_count - 1)
        trips.append(
            LinehaulPlan(
                trip_id=f"LH-{rng_hex(rng, 3)}",
                origin=ROAD_ORIGINS[i % len(ROAD_ORIGINS)],
                planned_arrival_minute=90 + i * 30 + rng.randint(-8, 8),
                volume=max(1, volume),
            )
        )
    trips.sort(key=lambda t: t.planned_arrival_minute)
    return trips


def random_disruptions(seed: int, *, intensity: float = 1.0) -> list[Disruption]:
    """Every real day has some friction. Seeded minor events — a short jam, a
    scanner drifting, a traffic incident — so no two days look the same and
    nothing about them is known in advance."""
    rng = random.Random(f"disruptions:{seed}")
    out: list[Disruption] = []
    if rng.random() < 0.5 * intensity:
        out.append(
            Disruption(
                kind="line_jam",
                at_minute=rng.randint(150, 420),
                duration_minutes=rng.randint(8, 25),
                target=str(rng.randint(1, 2)),
                source="random",
            )
        )
    if rng.random() < 0.4 * intensity:
        out.append(
            Disruption(
                kind="scanner_degradation",
                at_minute=rng.randint(150, 420),
                duration_minutes=rng.randint(30, 90),
                target=str(rng.randint(1, 2)),
                magnitude=round(rng.uniform(2, 4), 1),
                source="random",
            )
        )
    if rng.random() < 0.6 * intensity:
        out.append(
            Disruption(
                kind="traffic_incident",
                at_minute=rng.randint(480, 600),
                duration_minutes=rng.randint(20, 60),
                target=rng.choice("NESW"),
                magnitude=rng.randint(10, 30),
                source="random",
            )
        )
    if rng.random() < 0.25 * intensity:
        out.append(
            Disruption(
                kind="weather",
                at_minute=rng.randint(660, 840),
                magnitude=round(rng.uniform(1.5, 3), 1),
                source="random",
            )
        )
    return out


def _base(name: str, description: str, seed: int, ofd_date: date, **plan_kwargs):
    return StationOpsConfig(
        name=name,
        description=description,
        seed=seed,
        ofd_date=ofd_date,
        linehauls=generate_linehaul_plan(seed, ofd_date, **plan_kwargs),
        disruptions=random_disruptions(seed),
    )


def _preset_normal(seed: int, ofd_date: date) -> StationOpsConfig:
    return _base(
        "normal_day",
        "A typical day: linehauls on plan, full labor plan — plus the usual seeded minor "
        "friction (a short jam, a drifting scanner, a traffic incident).",
        seed,
        ofd_date,
    )


def _preset_ferry(seed: int, ofd_date: date) -> StationOpsConfig:
    cfg = _base(
        "ferry_disruption",
        "Weather on the PORT-X crossings: ferry-borne linehauls run 2.5-3.5h late. The "
        "truckfile's ferry checks reveal the delay progressively through the night.",
        seed,
        ofd_date,
    )
    rng = random.Random(f"ferry-preset:{seed}")
    for trip in cfg.linehauls:
        if trip.via_ferry and trip.planned_arrival_minute > 150:
            true = rng.randint(150, 210)
            trip.delay_minutes = true
            trip.revisions = [
                FerryRevision(reveal_minute=0, delay_minutes=round(true * 0.35)),
                FerryRevision(reveal_minute=150, delay_minutes=round(true * 0.75)),
                FerryRevision(reveal_minute=270, delay_minutes=true),
            ]
            trip.delay_reason = "ferry delayed: adverse weather (synthetic)"
    return cfg


def _preset_outage(seed: int, ofd_date: date) -> StationOpsConfig:
    cfg = _base(
        "induct_line_outage",
        "Induct line 1 jams at 03:00 (motor fault, ~2.5h) and line 2 at 05:00 (~1h), with a "
        "drifting scanner raising no-reads — none of it known in advance.",
        seed,
        ofd_date,
    )
    cfg.disruptions += [
        Disruption(kind="line_jam", at_minute=180, duration_minutes=150, target="1"),
        Disruption(kind="line_jam", at_minute=300, duration_minutes=60, target="2"),
        Disruption(
            kind="scanner_degradation",
            at_minute=120,
            duration_minutes=360,
            target="2",
            magnitude=2.5,
        ),
    ]
    return cfg


def _preset_labor(seed: int, ofd_date: date) -> StationOpsConfig:
    cfg = _base(
        "labor_shortage",
        "Attendance shortfall (~88%) and two stowers leaving at 04:30 — stow capacity and "
        "pick labor both run short.",
        seed,
        ofd_date,
    )
    cfg.labor.attendance_rate = 0.88
    cfg.disruptions.append(
        Disruption(kind="absenteeism", at_minute=270, target="stow", magnitude=2)
    )
    return cfg


def _preset_peak(seed: int, ofd_date: date) -> StationOpsConfig:
    cfg = _base(
        "peak_volume",
        "Peak day: 50% more volume on the same labor plan and route count, higher missort "
        "rate from temporary staff, and an unplanned surge at 04:00.",
        seed,
        ofd_date,
        total_volume=18000,
    )
    cfg.sort.missort_rate = 0.015
    cfg.disruptions.append(Disruption(kind="volume_surge", at_minute=240, magnitude=600))
    return cfg


def _preset_dispatch(seed: int, ofd_date: date) -> StationOpsConfig:
    cfg = _base(
        "dispatch_disruption",
        "Outbound stress: DSP-DELTA's drivers run late, a traffic incident hits the southern "
        "sector at 08:40, and afternoon weather raises failed attempts.",
        seed,
        ofd_date,
    )
    for d in cfg.dispatch.dsps:
        if d.code == "DSP-DELTA":
            d.late_rate = 0.5
        if d.code == "DSP-BRAVO":
            d.late_rate = 0.25
    cfg.disruptions += [
        Disruption(
            kind="traffic_incident", at_minute=520, duration_minutes=60, target="S", magnitude=30
        ),
        Disruption(kind="weather", at_minute=780, magnitude=2.5),
    ]
    return cfg


PRESETS = {
    "normal_day": _preset_normal,
    "ferry_disruption": _preset_ferry,
    "induct_line_outage": _preset_outage,
    "labor_shortage": _preset_labor,
    "peak_volume": _preset_peak,
    "dispatch_disruption": _preset_dispatch,
}


def build_preset(name: str, seed: int = 1, ofd_date: date = date(2026, 1, 1)) -> StationOpsConfig:
    """`name` is looked up in a fixed allow-list (like
    resolve_shipped_scenario_path) — never used to touch the filesystem."""
    try:
        factory = PRESETS[name]
    except KeyError as exc:
        raise KeyError(f"no station-ops preset named {name!r}") from exc
    return factory(seed, ofd_date)


def list_presets() -> list[dict]:
    return [
        {"name": n, "description": f(1, date(2026, 1, 1)).description} for n, f in PRESETS.items()
    ]
