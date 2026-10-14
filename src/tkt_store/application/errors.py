"""Failures that belong to persistence and the transaction loop.

These are the ways a transaction can fail for reasons OTHER than the rules
saying no. A refusal is not here — it is a value (`domain.outcomes.Refusal`),
not an exception. All of these extend `domain.errors.TktError`.
"""

from __future__ import annotations

from tkt_store.domain.errors import TktError
from tkt_store.domain.outcomes import Refusal


class Conflict(TktError):
    """The store's head moved since the snapshot (compare-and-swap lost)."""

    def __init__(self, expected: str | None, actual: str | None) -> None:
        super().__init__(f"store moved: expected {expected}, found {actual}")
        self.expected = expected
        self.actual = actual


class RetriesExhausted(TktError):
    """The transaction lost the race too many times. Re-running the op is safe."""


class StoreError(TktError):
    """The store failed: git error, remote unreachable, corrupt or unreadable data."""


class RefusedError(TktError):
    """Raised by the service facade when callers prefer exceptions to Outcome values."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(f"{refusal.code.value}: {refusal.message}")
        self.refusal = refusal
