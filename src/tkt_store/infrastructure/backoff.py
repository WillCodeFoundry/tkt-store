"""Exponential backoff with full jitter, measured in attempts (ADR 0001).

Contending writers that retry at once collide again: in the GitHub benchmark, ten
agents retrying immediately wasted 90% of their pushes. Waiting a random time from a
growing window spreads them out, but only if the window is on the scale of an attempt
(fetch, decide, push: seconds against GitHub, milliseconds against a local ref). So the
window is counted in "slots", like Ethernet's backoff: one slot is how long the attempt
that just lost took, from `begin()` to the call of the wait it returned.

Sleeping, the monotonic clock and randomness are injected (they live in `clock` and
`ids`), so this module is plain arithmetic and testable with fakes. The backoff itself
keeps no state between calls, so it can be shared (this says nothing about the rest of
the stack: one process per clone, design.md §7).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tkt_store.application.backoff import WaitAfterLoss

BACKOFF_CAP = 60.0
"""Seconds: no single wait exceeds this. It bounds the total: with 10 attempts, at most
9 waits, so at most 9 minutes of waiting plus the attempts themselves, whatever they
take; with ~3.5 s attempts against GitHub, about 6 minutes at worst and 3 on average.
Keep it at or below 60 s: renewing at two-thirds of a 30-minute lease leaves 10 minutes,
plus the 60 s grace, before anyone can take the claim over (docs/cli.md)."""
MIN_SLOT = 0.05
"""Seconds: the smallest slot, so a very fast attempt (a local ref) still spreads out."""


@dataclass(frozen=True)
class JitteredBackoff:
    """Before retry n, wait `jitter() * min(cap, slot * 2**(n-1))` seconds: `jitter()` is
    uniform in [0, 1) ("full jitter") and `slot` is how long the losing attempt took,
    at least `min_slot`."""

    sleep: Callable[[float], None]
    jitter: Callable[[], float]
    monotonic: Callable[[], float]
    cap: float = BACKOFF_CAP
    min_slot: float = MIN_SLOT

    def window(self, attempt: int, slot: float) -> float:
        """The upper bound of the wait before retry `attempt + 1`."""
        return min(self.cap, max(self.min_slot, slot) * 2.0 ** (attempt - 1))

    def begin(self) -> WaitAfterLoss:
        began = self.monotonic()

        def wait_after_loss(attempt: int) -> None:
            slot = self.monotonic() - began
            self.sleep(self.jitter() * self.window(attempt, slot))

        return wait_after_loss
