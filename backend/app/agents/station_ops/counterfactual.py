"""Robust counterfactual planning over *belief futures*.

The agent never gets to replay the true future (that would be an oracle no
real station has). Instead it builds K belief configs from what is known at
the decision minute:
- the past is replayed exactly: same config, plus every action and every
  disruption that has *already* happened (the twin's applied log);
- future disruptions that haven't happened are unknown, so they are absent;
- in-transit linehauls arrive at their *revealed* ETA plus sampled ETA error;
- drivers who haven't left yet get freshly sampled lateness from their DSP's
  reliability; drivers already on the move keep their true behaviour; a
  suspected no-show is treated as a no-show.

Each candidate is scored in every future against that future's baseline; the
plan's robust score is mean − λ·stdev, so a plan that only works if the
uncertain future breaks its way is penalised. The result is still a
*simulated* outcome, never a claim about a real station.
"""

import math
import random
import statistics

from pydantic import BaseModel

from app.agents.station_ops.mitigations import Candidate
from app.simulation.station_ops.config import StationOpsConfig
from app.simulation.station_ops.model import Intervention, StationOpsTwin
from app.simulation.station_ops.snapshot import run_station_day

SCORE_WEIGHTS = {"dea_pp": 1.0, "otd_pp": 0.5, "timely_staged_pp": 0.25, "labor_hour": -0.02}
ROBUSTNESS_LAMBDA = 0.5
SCORE_VERSION = "2026-11-09.1"


class Outcome(BaseModel):
    dea: float
    otd: float
    timely_staged: float
    rolled_over: int
    left_behind: int
    not_attempted: int


class Evaluation(BaseModel):
    name: str
    interventions: list[Intervention]
    labor_hours: float
    outcome: Outcome
    delta_dea_pp: float
    delta_otd_pp: float
    delta_timely_staged_pp: float
    score: float
    score_stdev: float = 0.0
    futures: int = 1


def _outcome(config: StationOpsConfig, interventions: list[Intervention]) -> Outcome:
    s = run_station_day(config, interventions)
    m = s.metrics
    return Outcome(
        dea=m["dea"].value or 0.0,
        # scored against the original wave plan, so moving a route can't game OTD
        otd=m["otd_original_plan"].value or 0.0,
        timely_staged=m["timely_staged"].value or 0.0,
        rolled_over=s.package_status["rolled_over"],
        left_behind=s.package_status["left_behind"],
        not_attempted=s.delivery["not_attempted"],
    )


def score(delta_dea_pp: float, delta_otd_pp: float, delta_ts_pp: float, labor: float) -> float:
    w = SCORE_WEIGHTS
    return round(
        w["dea_pp"] * delta_dea_pp
        + w["otd_pp"] * delta_otd_pp
        + w["timely_staged_pp"] * delta_ts_pp
        + w["labor_hour"] * labor,
        3,
    )


def applied_log(twin: StationOpsTwin) -> list[Intervention]:
    """Everything that has happened to this twin, as replayable inputs —
    actions *and* disruptions that already occurred."""
    return [
        Intervention(
            kind=a["kind"],
            amount=a["amount"],
            at_minute=a["minute"],
            target=a.get("target"),
            params=a.get("params") or {},
            source=a["source"],
        )
        for a in twin.applied
    ]


def belief_configs(twin: StationOpsTwin, k: int) -> list[StationOpsConfig]:
    now = twin.now_minute
    out = []
    for j in range(k):
        cfg = twin.config.model_copy(deep=True)
        rng = random.Random(f"belief:{cfg.seed}:{int(now)}:{j}")
        cfg.disruptions = []  # occurred ones are replayed from the applied log
        for i, plan in enumerate(cfg.linehauls):
            if twin.trips[i].status != "in_transit" or plan.cancelled:
                plan.revisions = []
                continue
            known = plan.known_delay(now)
            if known > 0:
                delay = max(0.0, known * (1 + rng.gauss(0, 0.15)))
            else:
                delay = rng.uniform(5, 40) if rng.random() < 0.05 else 0.0
            delay = max(delay, now - plan.planned_arrival_minute + 5)
            plan.delay_minutes, plan.revisions = delay, []
        cfg.driver_seed = f"{cfg.seed}:belief:{int(now)}:{j}"
        overrides = {}
        for d in twin.drivers:
            if d.standby:
                continue
            overdue = d.leave_at is None and twin.env.now > twin.planned_leave(d) + 15 * 60
            if d.leave_at is not None:
                overrides[d.route] = {
                    "late_s": d.late_s,
                    "recoverable_s": d.recoverable_s,
                    "no_show": False,
                }
            elif overdue:
                overrides[d.route] = {
                    "no_show": d.no_show or d.notified_at is not None,
                    "late_s": max(d.late_s, twin.env.now - twin.planned_leave(d)),
                }
        cfg.driver_overrides = overrides
        out.append(cfg)
    return out


def evaluate(
    config: StationOpsConfig | None,
    applied: list[Intervention],
    candidates: list[Candidate],
    *,
    twin: StationOpsTwin | None = None,
    futures: int = 1,
    try_combination: bool = True,
) -> tuple[Outcome, list[Evaluation]]:
    """With `twin`, evaluates over `futures` belief configs (realistic);
    without, replays `config` exactly (used for after-the-fact outcome
    checks on fresh seeds, where the whole day is the experiment)."""
    if twin is not None:
        configs = belief_configs(twin, max(1, futures))
        applied = applied_log(twin)
    else:
        configs = [config]
    return evaluate_prepared(configs, applied, candidates, try_combination=try_combination)


def evaluate_prepared(
    configs: list[StationOpsConfig],
    applied: list[Intervention],
    candidates: list[Candidate],
    *,
    try_combination: bool = True,
) -> tuple[Outcome, list[Evaluation]]:
    """The heavy part — touches no live twin, so it can run outside the
    session lock while the live day keeps moving."""
    baselines = [_outcome(cfg, applied) for cfg in configs]

    def run(c: Candidate) -> Evaluation:
        scores, outs, d_dea, d_otd, d_ts = [], [], [], [], []
        for cfg, base in zip(configs, baselines, strict=True):
            o = _outcome(cfg, [*applied, *c.interventions])
            dd = (o.dea - base.dea) * 100
            do = (o.otd - base.otd) * 100
            dt = (o.timely_staged - base.timely_staged) * 100
            outs.append(o)
            d_dea.append(dd)
            d_otd.append(do)
            d_ts.append(dt)
            scores.append(score(dd, do, dt, c.labor_hours))
        mean = statistics.fmean(scores)
        sd = statistics.pstdev(scores) if len(scores) > 1 else 0.0
        return Evaluation(
            name=c.name,
            interventions=c.interventions,
            labor_hours=c.labor_hours,
            outcome=outs[0],
            delta_dea_pp=round(statistics.fmean(d_dea), 3),
            delta_otd_pp=round(statistics.fmean(d_otd), 3),
            delta_timely_staged_pp=round(statistics.fmean(d_ts), 3),
            score=round(mean - ROBUSTNESS_LAMBDA * sd, 3),
            score_stdev=round(sd, 3),
            futures=len(configs),
        )

    results = [run(c) for c in candidates]
    if try_combination:
        positive = sorted((r for r in results if r.score > 0), key=lambda r: -r.score)
        if len(positive) >= 2:
            first = positive[0]
            kinds = {iv.kind for iv in first.interventions}
            second = next(
                (r for r in positive[1:] if not kinds & {iv.kind for iv in r.interventions}), None
            )
            if second is not None:
                results.append(
                    run(
                        Candidate(
                            name=f"{first.name} + {second.name}",
                            interventions=[*first.interventions, *second.interventions],
                            labor_hours=round(first.labor_hours + second.labor_hours, 2),
                        )
                    )
                )
    results.sort(key=lambda r: -r.score)
    base = baselines[0]
    return base, results


def is_finite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))
