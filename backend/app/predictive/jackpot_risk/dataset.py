"""Dataset construction for the jackpot-accumulation-risk predictive
model (Milestone 8, docs/ENGINEERING_ROADMAP.md) — the roadmap's "start
with the one best supported by Milestone 2-4 data" candidate: every
feature and label here derives from the Milestone 2 event log and the
Milestone 4 digital twin directly. Deliberately has no dependency on
the `rl` extra (app/rl/) — re-implements the small amount of
interval-stepping logic it needs rather than importing
StowBalancingEnv, so this module only needs the base simulation stack.

Feature provenance (every column traces to a named source, nothing
invented):

- `mean_hamper_occupancy` / `max_hamper_occupancy`: aggregated from the
  twin's own per-aisle `_Hamper.level / _Hamper.capacity`
  (`app/simulation/model.py`) — aggregated rather than per-aisle so the
  schema doesn't depend on a specific aisle count/layout.
- `stower_utilization`: the twin's `stower_pool` capacity/users.
- `current_backlog`: identical formula to
  `docs/OPERATIONAL_DOMAIN_MODEL.md`'s jackpot volume metric contract —
  count of `parcel.sort_attempted` events with `outcome == "jackpot"`
  minus count of `parcel.jackpot_cleared` events, both cumulative as of
  this row's timestamp.

`parcels_inducted` (cumulative count of `parcel.inducted` events) and
`trucks_remaining` (the twin's own truck-arrival counter) are computed
and kept in every row for diagnostic transparency, but are
**deliberately excluded from `FEATURE_COLUMNS`** — a real bug/design
flaw caught empirically before shipping (see
`docs/PREDICTIVE_INTELLIGENCE_SPEC.md` "A real finding caught before
shipping"): in the shipped scenario, truck arrivals are on a fixed
schedule, so `trucks_remaining` and `parcels_inducted` are almost
perfectly anti-correlated (measured: -1.0) and together act as a
trivial "how far into the run are we" clock, not genuine operational
risk signal. A model trained with them included scored far higher
(0.96 accuracy) than one trained without (0.78) — the first number was
real but misleading: it mostly reflects memorizing *when in a fixed
schedule* backlog typically grows, not reading *operational state* to
assess risk. `FEATURE_COLUMNS` below ships the honest, state-only set.

Label (`label_backlog_grows`): 1 if the backlog at `t + horizon_seconds`
is strictly greater than the backlog at `t`, else 0.

**Leakage boundary, enforced explicitly**: every FEATURE at row `t`
is computed only from events with `occurred_at <= t` (the snapshot is
taken before advancing to the next interval). Only the LABEL looks
ahead, to `t + horizon_seconds`. A row whose horizon window would
extend past the episode's actual end is dropped outright, not given a
placeholder label — there's no future to honestly label it with.
"""

import statistics
from dataclasses import dataclass

import pandas as pd

from app.events.event_types import PARCEL_INDUCTED, PARCEL_JACKPOT_CLEARED, PARCEL_SORT_ATTEMPTED
from app.simulation.config import ScenarioConfig, load_scenario
from app.simulation.model import aisle_codes_for, setup_simulation

#: The genuine operational-state features a model is trained/predicts
#: on. `parcels_inducted`/`trucks_remaining` are computed per row (see
#: module docstring) but excluded here deliberately, not by oversight.
FEATURE_COLUMNS = [
    "mean_hamper_occupancy",
    "max_hamper_occupancy",
    "stower_utilization",
    "current_backlog",
]

#: Every column a row actually carries — superset of FEATURE_COLUMNS,
#: kept for diagnostics (e.g. re-deriving the clock-proxy correlation
#: above) without being fed to a model.
ALL_COLUMNS = [*FEATURE_COLUMNS, "parcels_inducted", "trucks_remaining"]

#: Safety cap on steps per episode — the twin terminates on its own
#: (trucks_remaining == 0 and parcels_in_flight == 0) well before this
#: for every shipped scenario; this only guards against an
#: unanticipated non-terminating configuration, never expected to bind.
_MAX_STEPS_SAFETY = 2000


@dataclass(frozen=True)
class DatasetSpec:
    scenario_path: str
    decision_interval_seconds: float = 60.0
    horizon_seconds: float = 300.0


def _snapshot_features(ctx, aisle_codes: list[str]) -> dict:
    occupancies = [ctx.hampers[code].level / ctx.hampers[code].capacity for code in aisle_codes]
    diverts = sum(
        1
        for e in ctx.events
        if e.event_type == PARCEL_SORT_ATTEMPTED and e.payload.get("outcome") == "jackpot"
    )
    clears = sum(1 for e in ctx.events if e.event_type == PARCEL_JACKPOT_CLEARED)
    inducted = sum(1 for e in ctx.events if e.event_type == PARCEL_INDUCTED)
    return {
        "mean_hamper_occupancy": statistics.fmean(occupancies) if occupancies else 0.0,
        "max_hamper_occupancy": max(occupancies) if occupancies else 0.0,
        "stower_utilization": (
            len(ctx.stower_pool.users) / ctx.stower_pool.capacity
            if ctx.stower_pool.capacity
            else 0.0
        ),
        "current_backlog": diverts - clears,
        "parcels_inducted": inducted,
        "trucks_remaining": ctx.trucks_remaining.value,
    }


def run_episode_snapshots(
    config: ScenarioConfig, seed: int, *, decision_interval_seconds: float, horizon_seconds: float
) -> list[dict]:
    """Runs one twin episode to completion, taking a feature snapshot
    every `decision_interval_seconds`, then builds labeled rows from
    the resulting time series per this module's leakage boundary.
    """
    episode_config = config.model_copy(update={"seed": seed})
    env, ctx = setup_simulation(episode_config)
    aisle_codes = aisle_codes_for(episode_config)

    timeline: list[tuple[float, dict]] = []
    step = 0
    while True:
        target = step * decision_interval_seconds
        if target > 0:
            env.run(until=target)
        features = _snapshot_features(ctx, aisle_codes)
        timeline.append((env.now, features))

        episode_closed = ctx.trucks_remaining.value == 0 and ctx.parcels_in_flight.value == 0
        if episode_closed or step >= _MAX_STEPS_SAFETY:
            break
        step += 1

    rows = []
    for i, (t, features) in enumerate(timeline):
        target_time = t + horizon_seconds
        future_backlog = next(
            (f["current_backlog"] for ft, f in timeline[i + 1 :] if ft >= target_time), None
        )
        if future_backlog is None:
            continue  # tail of the episode — no honest future to label with
        rows.append(
            {
                **features,
                "seed": seed,
                "t": t,
                "label_backlog_grows": int(future_backlog > features["current_backlog"]),
            }
        )
    return rows


def build_dataset(spec: DatasetSpec, seeds: list[int]) -> pd.DataFrame:
    config = load_scenario(spec.scenario_path)
    all_rows = []
    for seed in seeds:
        all_rows.extend(
            run_episode_snapshots(
                config,
                seed,
                decision_interval_seconds=spec.decision_interval_seconds,
                horizon_seconds=spec.horizon_seconds,
            )
        )
    return pd.DataFrame(all_rows)


def temporal_train_test_split(
    df: pd.DataFrame, train_seeds: list[int], test_seeds: list[int]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits by episode (seed), never by shuffling individual rows —
    `train_seeds`/`test_seeds` are disjoint by construction (the
    caller's responsibility; asserted here) and the caller is expected
    to pass them in ascending order as a proxy for "earlier" vs.
    "later" runs, since these are independent synthetic episodes with
    no real calendar timestamp to split on. This is an explicit,
    honest substitute for a real chronological split, not a claim that
    seed order IS calendar time.
    """
    if set(train_seeds) & set(test_seeds):
        raise ValueError("train_seeds and test_seeds must be disjoint")
    train_df = df[df["seed"].isin(train_seeds)].reset_index(drop=True)
    test_df = df[df["seed"].isin(test_seeds)].reset_index(drop=True)
    return train_df, test_df
