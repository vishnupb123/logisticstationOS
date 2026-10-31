# StationOS — Engineering Handoff

**Purpose of this file**: the persistent, single source of truth for "where StationOS actually stands," written so a new engineering session (human or AI) can continue without this conversation's history. If something here conflicts with a doc in `docs/`, the more detailed doc wins for *content*; this file wins for *current status and what to do next*.

Last updated: 2026-10-31 (Milestone 8 completed this session).

---

## 1. Current milestone status

| Milestone | Status |
|---|---|
| 1 — Software foundation | ✅ Complete |
| 2 — Domain model and event infrastructure (Cycle 1 slice) | ✅ Complete |
| 3 — Data engineering and analytics | ✅ Complete |
| 4 — Digital twin | ✅ Complete |
| 5 — Agentic AI system | ✅ Complete |
| 6 — Reinforcement-learning environment | ✅ Complete |
| 7 — Agent and RL coordination | ✅ Complete |
| 8 — Predictive intelligence | ✅ **Complete** (this session) |
| 9 — Governance and reliability | Not started — **next** |
| 10 | Not started |

Full milestone definitions: `docs/ENGINEERING_ROADMAP.md`. Frontend (Milestone 10) remains explicitly deferred per the previous session's handoff — still not scoped, needs its own conversation.

## 2. What was built this session (Milestone 8)

**Chosen candidate**: jackpot accumulation risk, out of the roadmap's six candidate areas — route readiness and dispatch delay risk need unbuilt Cycle 2 data; the others overlap this one's state or fit the forecasting-shaped deliverable less naturally. Full rationale in the new `docs/PREDICTIVE_INTELLIGENCE_SPEC.md`.

**`backend/app/predictive/jackpot_risk/`** (new module, Layer 3 — "forecasts" per `docs/SYSTEM_ARCHITECTURE.md`'s original Layer 3 description):
- `dataset.py`: builds a labeled, per-decision-interval dataset from many Milestone 4 twin episodes. Features are aggregated hamper occupancy, stower utilization, and current backlog (identical formula to the Milestone 3 jackpot-volume metric contract); label is whether backlog grows over the next `horizon_seconds` (default 300s). Explicit leakage boundary: features only look backward, only the label looks ahead; trailing rows with no honest future are dropped, not padded. `temporal_train_test_split` splits by episode/seed (ascending order as an explicit, documented stand-in for "earlier vs. later," never real calendar time) and raises on any train/test seed overlap.
- `model.py`: two baselines (`BaseRatePredictor`, `CurrentBacklogHeuristic`) plus `LogisticRegressionRiskModel` (scaled sklearn logistic regression, the new `predictive` extra — scikit-learn/joblib, not a base dependency). All three share one `fit(X, y)` / `predict_proba(X) -> 1D array` interface.
- `evaluation.py`: shared accuracy/precision/recall/F1/ROC-AUC computation (ROC-AUC honestly `None` when only one class is present, not a crash).
- `schemas.py`: `JackpotRiskPrediction` + `to_finding` — the first `prediction`-category evidence finding sourced from a real trained model rather than an LLM, with the predicted probability doubling as the confidence/uncertainty indicator.
- `predict.py`: versioned model persistence (`MODEL_VERSION`) — `load_model` refuses a saved model whose feature schema no longer matches the current code, rather than silently predicting on misaligned columns.

**`backend/scripts/train_jackpot_risk_model.py`**: builds the dataset, does the temporal split, trains/evaluates all three candidates on held-out test episodes of the primary scenario *and* on two scenario variations never trained on (the same held-out-scenario rigor `docs/RL_ENVIRONMENT_SPEC.md` applied to the RL policy comparison), saves the trained model, writes a JSON report. Verified reproducible: re-running produces a byte-identical report.

**20 new tests** (111 → 131 total): dataset/leakage-boundary/temporal-split tests, baseline/model unit tests (including a toy-signal test proving the logistic regression learns the right direction), evaluation-metric edge cases, evidence-schema tests, and model-persistence round-trip tests (including stale-schema rejection).

## 3. A real finding caught before shipping (read this before touching `FEATURE_COLUMNS`)

The first feature set included `parcels_inducted` and `trucks_remaining`. A model trained on them scored a suspiciously high **0.961 accuracy / 0.985 ROC-AUC** on held-out episodes. Investigated rather than reported at face value: those two features are measured at **correlation -1.0** in the shipped (fixed-truck-arrival-schedule) scenario — together they're just a "how far into the run are we" clock, confirmed by the trained model's own coefficients (`trucks_remaining` +4.21, `parcels_inducted` -4.21, dwarfing every genuine operational feature, with `current_backlog` even carrying the wrong sign once the clock proxy was available to lean on instead).

**Fix**: those two columns are still computed per row (`ALL_COLUMNS`, for diagnostics) but excluded from `FEATURE_COLUMNS` — the set actually fed to a model. The honest result below is what shipped. General lesson: a model trained on simulated data from a scenario with a deterministic arrival schedule can trivially "predict the future" by learning the schedule itself — always check a surprisingly strong result's coefficients/feature importances before trusting it.

## 4. The results, run for real

Primary scenario (`rl_stow_balancing.yaml`), held-out test episodes (seeds 41-60, never trained on):

| Candidate | Accuracy | Precision | Recall | ROC-AUC |
|---|---|---|---|---|
| `base_rate` | 0.505 | 0.505 | 1.000 | 0.500 |
| `current_backlog_heuristic` | 0.350 | 0.405 | 0.615 | 0.347 |
| `logistic_regression` | **0.783** | **0.791** | 0.773 | **0.857** |

Held-out *scenario variations* (seeds 201-220, never trained on or used for model selection):

| Held-out scenario | `logistic_regression` accuracy | ROC-AUC |
|---|---|---|
| `held_out_high_volume` | 0.759 | 0.722 |
| `held_out_tighter_capacity` | 0.683 | 0.732 |

**Unlike Milestone 6's cautionary RL result, this is a genuine positive finding.** The model clearly beats both baselines using only real operational state, and degrades gracefully (not catastrophically) on scenario variations it never saw. Worth noting: the "intuitive" heuristic baseline (`current_backlog_heuristic`) actually performs *worse* than guessing the base rate (0.347 vs. 0.500 ROC-AUC) — a reminder that an intuitive-sounding rule isn't automatically a good one, and exactly why a baseline comparison is run at all rather than assumed.

## 5. Deliberate design choice: not wired into any agent or decision

`to_finding` exists and produces a correctly-tagged `prediction` Finding, but nothing in `app/agents/` or `app/security/decision_service.py` calls it. Same reasoning as Milestones 6/7's non-integration of the trained RL policy: a first model's limitations (synthetic data, one scenario family, moderate held-out-scenario degradation) should be read and weighed by whoever wires it in next, not silently assumed away. Tracked in `docs/OPEN_QUESTIONS.md`.

## 6. Known limitations

- **Drift monitoring is a written plan, not running code** (`docs/PREDICTIVE_INTELLIGENCE_SPEC.md` §"Drift-monitoring plan") — there's no live/production inference loop yet to monitor, the same reasoning OpenTelemetry was deferred.
- **Only one candidate area is built.** The other five (inbound volume forecasting, stow bottleneck prediction, route readiness, dispatch delay risk, parcel reconciliation anomalies) are explicitly not attempted this milestone, per the roadmap's own "validate the pattern on one" non-goal. Route readiness/dispatch delay risk specifically can't be built yet — they need Cycle 2 data that doesn't exist.
- **Trained and evaluated on one scenario family** (`rl_stow_balancing.yaml` + two parameter variations) — generalization to a meaningfully different layout/scenario is untested.
- The `OllamaProvider` live-verification gap and the tests-vs-dev-database footgun from prior milestones are unchanged (the latter was not hit this session — predictive-module tests need no database at all).

## 7. Open questions

Full register: `docs/OPEN_QUESTIONS.md`. New this session: should the jackpot-risk prediction be wired into an agent/decision as evidence (leaning: not yet — same bar as the RL policy); should the next predictive candidate area be built (unresolved — only when a future milestone's scope calls for it); real drift-monitoring implementation (unresolved — needs a live serving path first). Unchanged: RBAC role model (Milestone 9); real risk/blast-radius model beyond the Milestone 7 stub; metric formulas still `requires_validation`; live `OllamaProvider` verification pending.

## 8. Security considerations

No change to governance stance. The predictive model trains and predicts entirely offline against the digital twin's synthetic output — same ADR-0006/ADR-0002 boundary the twin and the RL environment already observe (never against live operational state, never claiming real-world predictive validity). No new secrets, credentials, or real data introduced. The new `predictive` extra (scikit-learn, joblib) is a standard, widely-used, reputable package set, consistent with `docs/SECURITY_AND_GOVERNANCE.md`'s dependency-review guidance.

## 9. Recommended next milestone

**Milestone 9 — Governance and reliability** (`docs/ENGINEERING_ROADMAP.md`): the rest of Layer 5 (RBAC/permission boundaries — `approved_by` on a `DecisionRecord` is still a plain string), secure configuration review, model/policy versioning (both the RL and predictive modules already have a version string — this milestone should establish the *system* for using it, not just the field), systematic error handling/retry-policy review, idempotency review, data validation, observability (OpenTelemetry — multiple agent/RL/predictive processes now exist, worth tracing), shadow-mode evaluation support.

**Frontend remains explicitly deferred** — unchanged from the prior session's note; still needs its own scoping conversation before any frontend code is written.

## 10. Exact instructions for the next session

1. Read this file, then `docs/ENGINEERING_ROADMAP.md` Milestone 9, then `docs/SECURITY_AND_GOVERNANCE.md` in full (it's the spec this milestone fills in) and ADR-0009's implementation note.
2. Confirm Milestones 1–8 still work: `cd backend && pip install -e ".[dev,analytics,rl,predictive]" && ruff check .`; bring up Postgres, `alembic upgrade head` (three migrations), `pytest -q` (131 tests). If `alembic upgrade head` silently no-ops, it's the documented tests-vs-dev-database footgun — drop `alembic_version` and retry.
3. RBAC is the centerpiece: design the role model (who can approve what class of `DecisionRecord`), wire it into `app/security/repository.py::approve_decision`/`reject_decision` so `approved_by` becomes a checked identity, not a trusted string. Don't let this leak into Milestone 7's existing `decision_service.py` coordination logic beyond what's needed — the coordination mechanism itself doesn't need to change, only who's allowed to call its approval functions.
4. Observability: `docs/SYSTEM_ARCHITECTURE.md` §Observability deferred OpenTelemetry "until there was more than one process/hop worth tracing — by now there is" (agents, RL training/eval, decision coordination, predictive training/eval). Revisit that deferral deliberately rather than leaving it stale.
5. Don't jump ahead of the roadmap — Milestone 9 is governance/reliability, not the frontend (10) or a second predictive model (would be re-opening Milestone 8's own non-goal).
6. When Milestone 9 is done: update this file's status table and date, run the full verification sequence from step 2 one more time and report the actual result, and update `docs/OPEN_QUESTIONS.md` for anything resolved or newly found.
