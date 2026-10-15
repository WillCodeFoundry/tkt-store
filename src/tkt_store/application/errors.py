"""Failures that belong to persistence and the transaction loop.

These are the ways a transaction can fail for reasons OTHER than the rules
saying no. A refusal is not here — it is a value (`domain.outcomes.Refusal`),
not an exception. All of these extend `domain.errors.TktError`.

Failures raised by `transact` carry the `op` that was being applied, with the ids
it was minted with, so a caller can re-run it with the same ids (design.md §6).
"""

from __future__ import annotations

from tkt_store.domain.errors import TktError
from tkt_store.domain.operations import Op
from tkt_store.domain.outcomes import Refusal
from tkt_store.domain.ticket import Revision


class Conflict(TktError):
    """The store's head moved since the snapshot (compare-and-swap lost) and nothing
    was published. Never raised after a commit reached the remote."""

    def __init__(self, expected: Revision | None, actual: Revision | None) -> None:
        super().__init__(f"store moved: expected {expected}, found {actual}")
        self.expected = expected
        self.actual = actual


class RetriesExhausted(TktError):
    """The transaction lost the race too many times; nothing was written. Re-running
    `op` (same ids) is safe."""

    def __init__(self, op: Op) -> None:
        super().__init__(f"retries exhausted for {type(op).__name__}")
        self.op = op


class StoreError(TktError):
    """The store failed: git error, remote unreachable, corrupt or unreadable data.

    `op` is set when the failure happened while applying an op. A failure during the
    push may mean the commit landed anyway: re-running `op` with the same ids is safe.
    """

    def __init__(self, message: str, *, op: Op | None = None) -> None:
        super().__init__(message)
        self.op = op


class RefusedError(TktError):
    """Raised by `raise_for_refusal` (in the service module) for callers that prefer
    exceptions to Outcome values."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(f"{refusal.code.value}: {refusal.message}")
        self.refusal = refusal
