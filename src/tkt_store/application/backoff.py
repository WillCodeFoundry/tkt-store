"""The backoff the transaction loop depends on between lost races.

A port: the application says WHEN an attempt begins and when one lost (after a
Conflict, before retrying), but not HOW LONG to wait or by what means; timing, waiting
and randomness belong to infrastructure. The production implementation is
`infrastructure.backoff.JitteredBackoff`, wired at the composition root. Without one,
the loop retries immediately (tests, simulations).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

WaitAfterLoss = Callable[[int], None]
"""Called with the attempt number (1-based) after that attempt lost a race, before the
next attempt. `transact` never calls it after the last attempt."""


class Backoff(Protocol):
    def begin(self) -> WaitAfterLoss:
        """Called as each attempt begins (before its snapshot). Returns how to wait if
        this attempt loses, so an implementation can scale the wait to how long the
        attempt took, without keeping state between calls."""
