"""The transaction loop (design.md §4): snapshot, decide, commit, retry.

Depends on the Store PORT only — never on a concrete store. This is the one
place that ties a pure decision to a durable commit, and the only place that
turns a lost race into a retry.
"""

from __future__ import annotations

from dataclasses import dataclass

from tkt_store.application.clock import Clock
from tkt_store.application.store import Store
from tkt_store.domain.operations import Op
from tkt_store.domain.outcomes import Apply, Refusal
from tkt_store.domain.ticket import Revision, Snapshot

DEFAULT_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class Committed:
    """The op was applied as a new revision."""

    revision: Revision
    decision: Apply
    snapshot_before: Snapshot


@dataclass(frozen=True)
class Unchanged:
    """The op was a no-op: its effect was already present. Nothing was written."""

    reason: str


@dataclass(frozen=True)
class Refused:
    """The rules declined the op. Nothing was written."""

    refusal: Refusal


Outcome = Committed | Unchanged | Refused


def transact(
    store: Store,
    op: Op,
    clock: Clock,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Outcome:
    """Snapshot -> decide -> commit against the snapshot's base; on Conflict, start over.

    - `now` is read once per attempt, so a decision and its timestamps agree
      (ticket times and `OpRecord.at`, which the store persists as tkt-time).
    - Refusal and NoOp return immediately; nothing is written.
    - After `max_attempts` conflicts, raise RetriesExhausted. Re-running is safe.
    - StoreError propagates unchanged.
    """
    raise NotImplementedError
