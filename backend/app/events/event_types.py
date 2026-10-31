"""Single source of truth for event-type strings — imported by the schemas
registry, the projector, the synthetic generator, and tests, so a typo
can't silently create a second, unvalidated "event type" of its own.
"""

TRUCK_ARRIVED = "truck.arrived"
TRUCK_UNLOADED = "truck.unloaded"
PARCEL_INDUCTED = "parcel.inducted"
PARCEL_CLASSIFIED = "parcel.classified"
PARCEL_SORT_ATTEMPTED = "parcel.sort_attempted"
PARCEL_JACKPOT_CLEARED = "parcel.jackpot_cleared"
PARCEL_STOWED = "parcel.stowed"
