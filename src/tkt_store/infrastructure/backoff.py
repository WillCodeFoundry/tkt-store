"""Exponential backoff with full jitter, between lost races (ADR 0001).

Contending writers that retry at once collide again: in the GitHub benchmark, ten
agents retrying immediately wasted 90% of their pushes. Waiting a random time from a
growing window spreads them out. Sleeping and randomness are injected (the system
clock and the random source live in `clock` and `ids`), so this module is plain
arithmetic and testable with fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

BACKOFF_BASE = 1.0
"""Seconds: the window after the first lost race (about a third of a GitHub commit)."""
BACKOFF_CAP = 16.0
"""Seconds: the window never grows past this."""


@dataclass(frozen=True)
class JitteredBackoff:
    """Before retry n, wait `jitter() * min(cap, base * 2**(n-1))` seconds, where
    `jitter()` is uniform in [0, 1) ("full jitter")."""

    sleep: Callable[[float], None]
    jitter: Callable[[], float]
    base: float = BACKOFF_BASE
    cap: float = BACKOFF_CAP

    def window(self, attempt: int) -> float:
        return min(self.cap, self.base * 2.0 ** (attempt - 1))

    def wait(self, attempt: int) -> None:
        self.sleep(self.jitter() * self.window(attempt))
