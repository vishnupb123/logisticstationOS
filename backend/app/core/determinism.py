"""Deterministic replacements for things that normally draw from the
global, unseeded random source — uuid.uuid4() chief among them.

Any code claiming to be reproducible given a seed (the synthetic event
generator, the digital twin) must build its UUIDs and other "random"
values from its own seeded random.Random, never from the system RNG. A
real bug from exactly this mistake briefly shipped in the Milestone 2
synthetic generator — every event_id/entity UUID came from the unseeded
global uuid.uuid4(), silently breaking the determinism it claimed to
have. These helpers exist so that mistake has no second place to happen.
"""

import random
import uuid


def rng_uuid(rng: random.Random) -> uuid.UUID:
    return uuid.UUID(int=rng.getrandbits(128), version=4)


def rng_hex(rng: random.Random, n_bytes: int) -> str:
    return rng.getrandbits(n_bytes * 8).to_bytes(n_bytes, "big").hex().upper()
