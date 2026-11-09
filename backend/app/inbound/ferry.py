"""Ferry-status providers. `FerryStatusProvider` is the seam a real
adapter would implement; the synthetic provider below is deterministic
per (seed, date, sailing, check number) so the truckfile's delay can
evolve realistically across refreshes in a night (on-time -> delayed ->
revised) while remaining reproducible in tests.
"""

import hashlib
import random
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel

FerryState = Literal["on_time", "delayed", "cancelled", "unknown"]

_REASONS = (
    "adverse weather on crossing",
    "late departure: port congestion",
    "vessel technical inspection",
    "high winds — reduced speed",
)


class FerryStatus(BaseModel):
    sailing: str
    status: FerryState
    delay_minutes: int
    reason: str | None
    checked_at: datetime
    provider: str


class FerryStatusProvider(Protocol):
    name: str

    def check(self, sailing: str, ofd_date: date, checked_at: datetime) -> FerryStatus: ...


class SyntheticFerryStatusProvider:
    """Weather is drawn per (seed, date): most nights are calm, some are
    rough (most sailings delayed), a few are severe (long delays, the odd
    cancellation). `force_weather` lets a demo pin one."""

    name = "synthetic_ferry_v1"

    def __init__(
        self, seed: int = 0, force_weather: Literal["calm", "rough", "severe"] | None = None
    ):
        self.seed = seed
        self.force_weather = force_weather

    def weather(self, ofd_date: date) -> str:
        if self.force_weather:
            return self.force_weather
        r = random.Random(f"weather:{self.seed}:{ofd_date.isoformat()}").random()
        return "calm" if r < 0.6 else "rough" if r < 0.9 else "severe"

    def check(self, sailing: str, ofd_date: date, checked_at: datetime) -> FerryStatus:
        key = f"{self.seed}:{ofd_date.isoformat()}:{sailing}"
        rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:12], 16))
        weather = self.weather(ofd_date)
        roll = rng.random()
        if weather == "calm":
            status, delay = (
                ("delayed", rng.randint(20, 60)) if roll < 0.15 else ("on_time", rng.randint(0, 10))
            )
        elif weather == "rough":
            status, delay = (
                ("delayed", rng.randint(60, 200))
                if roll < 0.75
                else ("on_time", rng.randint(0, 15))
            )
        else:
            if roll < 0.12:
                status, delay = "cancelled", 0
            else:
                status, delay = "delayed", rng.randint(150, 300)
        reason = None if status == "on_time" else rng.choice(_REASONS) + " (synthetic)"
        return FerryStatus(
            sailing=sailing,
            status=status,
            delay_minutes=delay,
            reason=reason,
            checked_at=checked_at,
            provider=self.name,
        )
