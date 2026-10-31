# Predictive Intelligence Specification

## Status: first model implemented and evaluated (Milestone 8, 2026-10-31)

`docs/ENGINEERING_ROADMAP.md` Milestone 8 names six candidate areas and asks for "at least one... start with the one best supported by Milestone 2-4 data." This is that first one: **jackpot accumulation risk**.

## Why this candidate, not the other five

- **Route readiness prediction** and **dispatch delay risk** need Cycle 2 (Pick & Stage, dispatch, waves, routes, vans) — not built (`docs/ENGINEERING_ROADMAP.md` scoped Cycle 1 only through Milestone 4). There is no data for these yet, not just an unvalidated metric.
- **Parcel reconciliation anomalies** is a different problem shape (outlier/anomaly detection on the event log) than the "dataset + temporal train/test + baseline + evaluation" pattern the other candidates fit naturally — better validated on a forecasting-shaped problem first.
- **Inbound volume forecasting** and **stow bottleneck prediction** are both plausible and M2-4-supported, but overlap heavily with jackpot accumulation risk's underlying state (hamper occupancy, stower utilization). Jackpot was chosen because it already has a named, contract-defined metric (`docs/OPERATIONAL_DOMAIN_MODEL.md` §4.1 "Jackpot volume") to predict *forward* from, rather than requiring a new target definition from scratch, and it continues the project's own running thread (Milestone 3's metric, Milestone 5's agent exit criteria, Milestone 6's RL problem, Milestone 7's decision-demo evidence all center on jackpot backlog).

Per the roadmap's own non-goal, the other five areas are **not** attempted this milestone — validate the pattern on one first.

## The prediction problem, as formalized

**Target**: will the jackpot backlog (`docs/OPERATIONAL_DOMAIN_MODEL.md`'s jackpot volume metric: cumulative `parcel.sort_attempted`-outcome-jackpot diverts minus cumulative `parcel.jackpot_cleared` clears) be strictly higher `horizon_seconds` (default 300s / 5 simulated minutes) from now than it is right now — a binary classification (`label_backlog_grows`), not a raw count regression, so the output is directly a risk probability.

**Features** (`app/predictive/jackpot_risk/dataset.py::FEATURE_COLUMNS`, aggregated across aisles so the schema doesn't depend on a specific layout):
- `mean_hamper_occupancy`, `max_hamper_occupancy` — from the twin's per-aisle hamper level/capacity.
- `stower_utilization` — the twin's stower-pool capacity/users.
- `current_backlog` — the same jackpot-volume formula, as of right now.

**Leakage boundary**: every feature at row `t` is computed only from events with `occurred_at <= t`; only the label looks ahead to `t + horizon_seconds`. A row whose horizon window would run past the episode's actual end is dropped, never padded with a placeholder.

## A real finding caught before shipping

The first feature set also included `parcels_inducted` (cumulative count of `parcel.inducted` events) and `trucks_remaining` (the twin's own counter) — plausible-looking features. A model trained with them scored **0.961 accuracy / 0.985 ROC-AUC** on held-out episodes of the same scenario — suspiciously high for a simple logistic regression on a modest synthetic dataset, so it was investigated rather than reported at face value (the same discipline that caught Milestone 2's UUID bug and Milestone 6's argsort/scenario-tuning bugs).

The cause: in the shipped scenario, truck arrivals are on a fixed schedule, so `trucks_remaining` and `parcels_inducted` are **measured at correlation -1.0** — together they're a trivial "how far into the run are we" clock, not genuine operational-state signal. The logistic regression's own coefficients confirmed it: `trucks_remaining` (+4.21) and `parcels_inducted` (-4.21) dwarfed every real operational feature (`max_hamper_occupancy` +2.74, `stower_utilization` +2.74, `mean_hamper_occupancy` +1.06, `current_backlog` -0.18 — note the wrong sign, further evidence it wasn't doing real work once the clock proxy was available).

**Fix**: `parcels_inducted`/`trucks_remaining` are still computed per row (kept in `ALL_COLUMNS` for diagnostics) but excluded from `FEATURE_COLUMNS` — the set a model is actually trained/predicts on. The honest, state-only result below is what shipped. This is a general lesson worth stating plainly: a model trained on simulated data from a scenario with a fixed, deterministic arrival schedule can trivially "predict the future" by learning the schedule itself, which is not a capability that would survive contact with a scenario where arrivals vary — always check a surprisingly strong result's feature coefficients/importances before trusting it.

## Dataset and temporal validation

Built from the twin (Milestone 4) running the shipped `rl_stow_balancing.yaml` scenario across many independent seeded episodes, snapshotting features every `decision_interval_seconds` (default 60s). **Temporal split, honestly operationalized**: these are independent synthetic episodes with no real calendar timestamp, so "temporal" is implemented as splitting by seed, in ascending order, treating lower seeds as "earlier" and higher seeds as "later" — training seeds and test seeds are always disjoint, enforced by `temporal_train_test_split` raising if they overlap. This is an explicit, labeled substitute for real chronological ordering, not a claim that seed order IS calendar time (the same honesty `docs/RL_ENVIRONMENT_SPEC.md` applies to "internal consistency, not real-world fidelity").

Default split: seeds 1-40 (train, 1022 rows) / 41-60 (test, 515 rows).

## Models

- `BaseRatePredictor`: predicts the training set's observed positive rate for every row, regardless of features — the floor any real signal must clear.
- `CurrentBacklogHeuristic`: a one-line rule a human might write ("predict growth iff backlog is already nonzero") — not learned, the same role `app/rl/baselines.py::RuleBasedPolicy` plays for the RL environment.
- `LogisticRegressionRiskModel`: a scaled logistic regression (the `predictive` extra — scikit-learn, not a base dependency). Deliberately simple and interpretable (its coefficients are exactly what caught the finding above) rather than a more complex model chosen to chase accuracy on a modest dataset.

Versioned via `MODEL_VERSION` (`app/predictive/jackpot_risk/model.py`), carried into every saved model file and every `JackpotRiskPrediction` — a prediction is always traceable to the exact model version that produced it.

## Evaluation protocol and results (ran 2026-10-31)

Primary scenario, held-out test episodes (seeds 41-60, never trained on):

| Candidate | Accuracy | Precision | Recall | ROC-AUC |
|---|---|---|---|---|
| `base_rate` | 0.505 | 0.505 | 1.000 | 0.500 |
| `current_backlog_heuristic` | 0.350 | 0.405 | 0.615 | 0.347 |
| `logistic_regression` | **0.783** | **0.791** | 0.773 | **0.857** |

Held-out *scenario variations* (seeds 201-220, never trained on, never seen during model selection — the same generalization check `docs/RL_ENVIRONMENT_SPEC.md` applied to the RL policy comparison):

| Held-out scenario | `logistic_regression` accuracy | ROC-AUC |
|---|---|---|
| `held_out_high_volume` (more trucks/parcels) | 0.759 | 0.722 |
| `held_out_tighter_capacity` (tighter hamper capacity) | 0.683 | 0.732 |

Verified reproducible: re-running the training script with the same seeds produces a byte-identical evaluation report.

### The honest read of these numbers

Unlike Milestone 6's RL result, this is a genuine positive finding: the model clearly beats both baselines on the primary scenario (0.857 vs. 0.500 ROC-AUC) using only real operational state, and the signal degrades gracefully rather than collapsing on held-out scenario variations (0.72-0.73 ROC-AUC, still well above the 0.5 baseline floor). It is not presented as more than it is: a *first*, narrow, interpretable model on *synthetic* data from *one* scenario family, evaluated honestly rather than cherry-picked — the `current_backlog_heuristic` baseline actually performs *worse* than base-rate guessing (0.347 ROC-AUC), a useful reminder that an intuitive-sounding rule isn't automatically a good one.

## Drift-monitoring plan (specified, not yet running code)

There is no live/production inference loop yet to monitor — this is the same reasoning `docs/SYSTEM_ARCHITECTURE.md` gives for deferring OpenTelemetry until there's more than one process/hop worth tracing. The plan, concrete enough to implement once a serving path exists:

1. **Feature-distribution drift**: track rolling-window means/stdevs of `mean_hamper_occupancy`, `max_hamper_occupancy`, `stower_utilization`, `current_backlog` against the training-set statistics stored alongside the model; alert if any feature's rolling mean shifts beyond, e.g., 2 training-set standard deviations.
2. **Prediction-distribution drift**: track the rolling mean predicted probability against the training-set base rate (0.505 here); a large, sustained shift suggests either real operational change or a scenario the model was never trained on.
3. **Label drift (if ground truth becomes available later)**: recompute the evaluation metrics above on a rolling window of recent *realized* outcomes once this problem has ground truth beyond synthetic episodes; retrain or roll back if accuracy degrades materially from the reported baseline.
4. **Versioning discipline**: never silently retrain-and-replace a deployed model file — bump `MODEL_VERSION`, keep the evaluation report for the new version, and let whichever consumer reads predictions see the version change.

## Relationship to the agentic layer

`app/predictive/jackpot_risk/schemas.py::to_finding` converts a prediction into the shared evidence-category scheme (`app/agents/schemas.py`), tagged `prediction` with the predicted probability as its confidence/uncertainty indicator — never presented as an `observation`. This is deliberately **not** wired into the Flow Intelligence Agent or `app/security/decision_service.py` this milestone, the same reasoning Milestone 6/7 gave for not wiring the trained RL policy into anything beyond its own evaluation report: a first model's output shouldn't be cited as agent/decision evidence before its limitations (synthetic data, one scenario family, moderate held-out-scenario degradation) have been read by whoever wires it in next. Tracked in `docs/OPEN_QUESTIONS.md`.

## Non-goals, maintained

- The other five candidate areas (inbound volume forecasting, stow bottleneck prediction, route readiness, dispatch delay risk, parcel reconciliation anomalies) — not attempted, per the roadmap's own "validate the pattern on one" non-goal.
- Deploying this model's output as an unflagged "fact" anywhere — it is a `prediction`, carrying a probability, not an `observation`.
- Any claim of real-world predictive validity — like the digital twin itself (ADR-0006), this is evaluated for internal consistency against synthetic data, not against real operations that don't exist for this project.
