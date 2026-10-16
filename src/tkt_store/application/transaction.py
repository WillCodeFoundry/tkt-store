"""The transaction loop (design.md §4): snapshot, decide, commit, retry.

Depends on the Store PORT only — never on a concrete store. This is the one
place that ties a pure decision to a durable commit, and the only place that
turns a lost race into a retry.
"""

from __future__ import annotations

from dataclasses import dataclass

from tkt_store.application.backoff import Backoff
from tkt_store.application.clock import Clock
from tkt_store.application.errors import Conflict, RetriesExhausted, StoreError
from tkt_store.application.store import Store
from tkt_store.domain.occupancy import states_after
from tkt_store.domain.operations import Op
from tkt_store.domain.outcomes import NoOp, OpRecord, Refusal
from tkt_store.domain.rules import decide
from tkt_store.domain.ticket import Revision, Snapshot, TicketId, TicketState

DEFAULT_MAX_ATTEMPTS = 10


@dataclass(frozen=True)
class Committed:
    """The op was applied as a new revision. `tickets`: the tickets it concerns, each with
    its open claim, after it."""

    revision: Revision
    record: OpRecord
    tickets: tuple[TicketState, ...]


@dataclass(frozen=True)
class Unchanged:
    """The op was a no-op: its effect was already present. Nothing was written.
    `tickets`: the tickets it concerns, each with its open claim, as they are now (e.g. the
    ticket a re-run claim already holds)."""

    reason: str
    tickets: tuple[TicketState, ...]


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
    backoff: Backoff | None = None,
) -> Outcome:
    """Snapshot -> decide -> commit against the snapshot's revision; on Conflict, start over.

    - `now` is read once per attempt, so a decision and its timestamps agree
      (ticket times and `OpRecord.at`, which the store persists as tkt-time).
    - Refusal and NoOp return immediately; nothing is written. A NoOp's
      `ticket_ids` are resolved against the snapshot into `Unchanged.tickets`.
    - Committed.tickets are the tickets the record names, as the Apply leaves them.
    - Each attempt starts with `backoff.begin()`; after a Conflict, the wait it returned
      is called with the attempt number before the next attempt (never after the last;
      no backoff means retry at once).
    - After `max_attempts` conflicts, raise RetriesExhausted(op).
    - A StoreError from the store is re-raised as StoreError(message, op=op) from the
      original, so the caller has the ids to re-run with.
    """
    for attempt in range(1, max_attempts + 1):
        wait_after_loss = None if backoff is None else backoff.begin()
        try:
            snapshot = store.snapshot()
        except StoreError as error:
            raise StoreError(str(error), op=op) from error
        decision = decide(snapshot, op, clock.now())
        if isinstance(decision, Refusal):
            return Refused(decision)
        if isinstance(decision, NoOp):
            return Unchanged(decision.reason, _states(snapshot, decision.ticket_ids))
        try:
            revision = store.commit(snapshot.revision, decision.changes, decision.record)
        except Conflict:
            if wait_after_loss is not None and attempt < max_attempts:
                wait_after_loss(attempt)
            continue
        except StoreError as error:
            raise StoreError(str(error), op=op) from error
        written = states_after(snapshot, decision.changes, decision.record.ticket_ids)
        return Committed(revision, decision.record, written)
    raise RetriesExhausted(op)


def _states(snapshot: Snapshot, ticket_ids: tuple[TicketId, ...]) -> tuple[TicketState, ...]:
    return states_after(snapshot, (), ticket_ids)
