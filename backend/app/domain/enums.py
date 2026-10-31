from enum import StrEnum


class ParcelClassification(StrEnum):
    """Outcome of the induct-time classification scan.

    docs/OPERATIONAL_DOMAIN_MODEL.md §3.1 step 4. Only NORMAL_CYCLE1 proceeds
    through sortation/stow in this milestone's scope — the others divert to
    exception workflows (high-value cage, etc.) that aren't modeled yet.
    """

    NORMAL_CYCLE1 = "normal_cycle1"
    SIDELINE = "sideline"
    HIGH_VALUE = "high_value"
    FUTURE_DATE = "future_date"
    EXCEPTION = "exception"


class ParcelLifecycleState(StrEnum):
    """Projected (virtual) state of a parcel, derived from its event
    history — never assumed to match physical reality; see
    Parcel.lifecycle_consistent.
    """

    INDUCTED = "inducted"
    CLASSIFIED = "classified"
    SORTED = "sorted"
    JACKPOTTED = "jackpotted"
    STOWED = "stowed"
    PENDING_EXCEPTION = "pending_exception"


class SortAttemptOutcome(StrEnum):
    SORTED = "sorted"
    JACKPOT = "jackpot"


class TruckStatus(StrEnum):
    SCHEDULED = "scheduled"
    ARRIVED = "arrived"
    UNLOADED = "unloaded"


class SortCluster(StrEnum):
    """docs/OPERATIONAL_DOMAIN_MODEL.md §2 — Cluster A (A1–A54), Cluster B
    (B1–B68) in the synthetic reference configuration. Configurable, not
    universal.
    """

    A = "A"
    B = "B"


class EventSourceKind(StrEnum):
    """What kind of real-world fact an event represents — distinct from
    *who* emitted it (see Event.source/provenance for that). Required by
    docs/DATA_ARCHITECTURE.md and the evidence-discipline principle in
    docs/PRODUCT_VISION.md: a projection built from events must be able to
    tell a sensor reading apart from a simulated or inferred one.
    """

    PHYSICAL_OBSERVATION = "physical_observation"
    SYSTEM_RECORDED = "system_recorded"
    INFERRED = "inferred"
    SIMULATED = "simulated"
