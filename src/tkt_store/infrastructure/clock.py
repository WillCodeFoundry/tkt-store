"""Concrete clocks. The ONLY module allowed to read the system clock.

Both satisfy the `application.clock.Clock` port structurally.
"""

from __future__ import annotations

import time

from tkt_store.domain.ticket import Timestamp


class SystemClock:
    def now(self) -> Timestamp:
        return int(time.time())


class FakeClock:
    """A deterministic clock for tests and simulations."""

    def __init__(self, start: Timestamp = 1_800_000_000) -> None:
        self._now = start

    def now(self) -> Timestamp:
        return self._now

    def advance(self, seconds: int) -> None:
        raise NotImplementedError

    def set(self, value: Timestamp) -> None:
        raise NotImplementedError
