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
        # half the road network lands the evening before and waits in the yard;
        # the rest runs overnight (site profile: shape, not data)
        arrive = (-480 + i * 90) if i < 5 else (30 + (i - 5) * 75)
        trips.append(
            LinehaulPlan(
                trip_id=f"LH-{rng_hex(rng, 3)}",
                origin=ROAD_ORIGINS[i % len(ROAD_ORIGINS)],
                planned_arrival_minute=arrive + rng.randint(-8, 8),
                volume=max(1, volume),
            )
        )
    trips.sort(key=lambda t: t.planned_arrival_minute)
    _add_trip_detail(trips, random.Random(f"linehaul-detail:{seed}:{ofd_date.isoformat()}"))
    return trips


CROSSDOCKS = ("XDOCK-C1", "XDOCK-C2")
PORT_PAIRS = {"PORT-X1": ("PORT-X1", "PORT-Y1"), "PORT-X2": ("PORT-X2", "PORT-Y2")}
TRIP_CROSSING_ROAD_MINUTES = 90


def _add_trip_detail(trips: list[LinehaulPlan], rng: random.Random) -> None:
    """Facility sequence (legs), operator type, assets and unplanned share —
    synthetic codes only."""
    for t in trips:
        arrive = t.planned_arrival_minute
        if t.via_ferry:
            dep_port, arr_port = PORT_PAIRS[t.origin]
            sail = arrive - 25 - FERRY_CROSSING_MINUTES
            t.legs = [
                {
                    "from": f"HUB-{t.origin[-2:]}",
                    "to": dep_port,
                    "mode": "road",
                    "planned_depart": sail - TRIP_CROSSING_ROAD_MINUTES - 30,
                    "planned_arrive": sail - 30,
                },
                {
                    "from": dep_port,
                    "to": arr_port,
                    "mode": "ferry",
                    "planned_depart": sail,
                    "planned_arrive": sail + FERRY_CROSSING_MINUTES,
                },
                {
                    "from": arr_port,
                    "to": "STATION",
                    "mode": "road",
                    "planned_depart": sail + FERRY_CROSSING_MINUTES,
                    "planned_arrive": arrive,
                },
            ]
            t.operator_type = "team"
        else:
            hops = (
                [t.origin] + ([rng.choice(CROSSDOCKS)] if rng.random() < 0.5 else []) + ["STATION"]
            )
            span = rng.randint(150, 330)
            step = span / (len(hops) - 1)
            t.legs = [
                {
                    "from": a,
                    "to": b,
                    "mode": "road",
                    "planned_depart": round(arrive - span + k * step),
                    "planned_arrive": round(arrive - span + (k + 1) * step),
                }
                for k, (a, b) in enumerate(zip(hops, hops[1:], strict=False))
            ]
            t.operator_type = "team" if span > 300 else "single"
        t.tractor = f"TR-{rng_hex(rng, 2)}"
        t.trailer = f"TL-{rng_hex(rng, 3)}"
        t.unplanned_share = round(rng.uniform(0.1, 0.35), 3)


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
                at_minute=rng.randint(180, 540),
                duration_minutes=rng.randint(8, 25),
                target=str(rng.randint(1, 2)),
                source="random",
            )
        )
    if rng.random() < 0.4 * intensity:
        out.append(
            Disruption(
                kind="scanner_degradation",
                at_minute=rng.randint(180, 540),
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
                at_minute=rng.randint(600, 720),
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
                at_minute=rng.randint(780, 960),
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
        "Weather on the PORT-X crossings: ferry-borne linehauls run 3.5-5h late. The "
        "truckfile's ferry checks reveal the delay progressively through the night.",
        seed,
        ofd_date,
    )
    rng = random.Random(f"ferry-preset:{seed}")
    for trip in cfg.linehauls:
        if trip.via_ferry and trip.planned_arrival_minute > 150:
            true = rng.randint(210, 300)
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
        "The automated line (L1) jams at 03:30 (motor fault, ~2.5h) and manual line L2 at "
        "05:30 (~1h), with a drifting scanner raising no-reads — none of it known in advance.",
        seed,
        ofd_date,
    )
    cfg.disruptions += [
        Disruption(kind="line_jam", at_minute=210, duration_minutes=150, target="1"),
        Disruption(kind="line_jam", at_minute=330, duration_minutes=60, target="2"),
        Disruption(
            kind="scanner_degradation",
            at_minute=150,
            duration_minutes=360,
            target="2",
            magnitude=2.5,
        ),
    ]
    return cfg


def _preset_labor(seed: int, ofd_date: date) -> StationOpsConfig:
    cfg = _base(
        "labor_shortage",
        "Attendance shortfall (~88%) and two stowers leaving at 05:30 — stow capacity and "
        "pick labor both run short.",
        seed,
        ofd_date,
    )
    cfg.labor.attendance_rate = 0.88
    cfg.disruptions.append(
        Disruption(kind="absenteeism", at_minute=330, target="stow", magnitude=2)
    )
    return cfg


def _preset_peak(seed: int, ofd_date: date) -> StationOpsConfig:
    cfg = _base(
        "peak_volume",
        "Peak day: 50% more volume on the same labor plan and route count, higher missort "
        "rate from temporary staff, and an unplanned surge at 04:30.",
        seed,
        ofd_date,
        total_volume=18000,
    )
    cfg.sort.missort_rate = 0.015
    cfg.disruptions.append(Disruption(kind="volume_surge", at_minute=270, magnitude=600))
    return cfg


def _preset_dispatch(seed: int, ofd_date: date) -> StationOpsConfig:
    cfg = _base(
        "dispatch_disruption",
        "Outbound stress: DSP-DELTA's drivers run late, a traffic incident hits the southern "
        "sector at 10:40, and afternoon weather raises failed attempts.",
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
            kind="traffic_incident", at_minute=640, duration_minutes=60, target="S", magnitude=30
        ),
        Disruption(kind="weather", at_minute=900, magnitude=2.5),
    ]
    return cfg


def _preset_pitch(seed: int, ofd_date: date) -> StationOpsConfig:
    """The demo day (HANDOFF_V2 Appendix C): a ferry delay revealed through
    the night, an unplanned surge, a finger running full, a grounded van and
    a busy tomorrow — every chapter of the station day has something to show."""
    cfg = _preset_ferry(seed, ofd_date)
    cfg.name = "pitch_day"
    cfg.description = (
        "Demo day: ferry linehauls 3.5–5h late (revealed progressively), an unplanned "
        "surge at 04:30, the automated line's scanner drifting, a grounded van at check-in "
        "and DSP lateness — with a busier tomorrow."
    )
    cfg.disruptions += [
        Disruption(kind="volume_surge", at_minute=270, magnitude=500),
        Disruption(
            kind="scanner_degradation", at_minute=330, duration_minutes=60, target="1", magnitude=3
        ),
    ]
    for d in cfg.dispatch.dsps:
        if d.code == "DSP-DELTA":
            d.late_rate = 0.3
    cfg.dispatch.vsa_ground_rate = 0.04
    return cfg


PRESETS = {
    "normal_day": _preset_normal,
    "ferry_disruption": _preset_ferry,
    "induct_line_outage": _preset_outage,
    "labor_shortage": _preset_labor,
    "peak_volume": _preset_peak,
    "dispatch_disruption": _preset_dispatch,
    "pitch_day": _preset_pitch,
}

#: Demo chapter bookmarks (sim minute, title) for presenter mode.
PITCH_CHAPTERS: list[tuple[float, str]] = [
    (60, "Before the shift: yard, plan, rotation"),
    (165, "Sort start: induct vs. dynamic target"),
    (390, "Mid-sort: stow WIP, fingers, quality"),
    (600, "Pick start: cycle decision"),
    (750, "Dispatch: vans, staging, work items"),
    (930, "After dispatch: close-out & tomorrow"),
]


def build_preset(
    name: str, seed: int = 1, ofd_date: date = date(2026, 1, 1), scale: float = 1.0
) -> StationOpsConfig:
    """`name` is looked up in a fixed allow-list (like
    resolve_shipped_scenario_path) — never used to touch the filesystem.
    `scale` multiplies volume, routes and the labour plan together (site
    profile; the real ranges are an open question, Q2)."""
    try:
        factory = PRESETS[name]
    except KeyError as exc:
        raise KeyError(f"no station-ops preset named {name!r}") from exc
    cfg = factory(seed, ofd_date)
    if scale != 1.0:
        apply_scale(cfg, scale)
    return cfg


def apply_scale(cfg: StationOpsConfig, scale: float) -> None:
    import math

    scale = max(0.25, min(4.0, scale))
    for t in cfg.linehauls:
        t.volume = max(1, round(t.volume * scale))
    for d in cfg.disruptions:
        if d.kind == "volume_surge":
            d.magnitude = round(d.magnitude * scale)
    cfg.outbound.routes = max(10, round(cfg.outbound.routes * scale))
    cfg.stow.stowers = max(2, round(cfg.stow.stowers * scale))
    cfg.induct.lines = max(2, math.ceil(cfg.induct.lines * scale))
    cfg.induct.automated_lines = max(1, math.ceil(cfg.induct.automated_lines * scale))
    cfg.labor.problem_solvers = max(1, round(cfg.labor.problem_solvers * scale))
    cfg.labor.dedicated_pickers = max(1, round(cfg.labor.dedicated_pickers * scale))
    cfg.labor.flex_pool = max(2, round(cfg.labor.flex_pool * scale))
    cfg.doors = max(2, math.ceil(cfg.doors * scale))
    cfg.dispatch.yard_marshals = max(2, round(cfg.dispatch.yard_marshals * scale))
    cfg.sort.finger_bay_capacity = round(cfg.sort.finger_bay_capacity * scale)
    cfg.closeout.roster_size = max(12, round(cfg.closeout.roster_size * scale))
    cfg.scale = scale


def list_presets() -> list[dict]:
    return [
        {"name": n, "description": f(1, date(2026, 1, 1)).description} for n, f in PRESETS.items()
    ]
