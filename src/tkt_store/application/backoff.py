"""The backoff the transaction loop depends on between lost races.

A port: the application decides WHEN to wait (after a Conflict, before retrying) but
not HOW LONG or by what means; waiting needs time and randomness, which only
infrastructure may touch. The production implementation is
`infrastructure.backoff.JitteredBackoff`, wired at the composition root. Without one,
the loop retries immediately (tests, simulations).
"""

from __future__ import annotations

from typing import Protocol


class Backoff(Protocol):
    def wait(self, attempt: int) -> None:
        """Called after the `attempt`-th lost race (1-based), before the next attempt.
        Never called after the last attempt."""
