"""TicketStore: the facade the coordinator and the CLI use.

Mints ids BEFORE transacting (invariant 7), runs ops through the transaction
loop, and returns its outcomes. Owns no rules of its own beyond that wiring. It
depends only on ports (Store, Clock, IdSource); the concrete implementations are
chosen at the composition root (`tkt_store.open_store`), never here.
"""

from __future__ import annotations

from collections.abc import Sequence

from tkt_store.application.clock import Clock
from tkt_store.application.errors import RefusedError
from tkt_store.application.ids import IdSource
from tkt_store.application.store import HistoryEntry, Store
from tkt_store.application.transaction import Outcome, Refused
from tkt_store.domain.status import Status
from tkt_store.domain.ticket import (
    AgentId,
    Claim,
    ClaimId,
    Duration,
    Kind,
    ProjectId,
    Snapshot,
    Stage,
    Ticket,
    TicketId,
)

DEFAULT_TTL: Duration = 30 * 60


class TicketStore:
    """All mutating methods return the transaction Outcome. Callers that prefer
    exceptions can wrap a call in `raise_for_refusal`, which raises on a refusal.

    Construct it with explicit dependencies, or use `tkt_store.open_store(repo)`
    for the production wiring.
    """

    def __init__(self, store: Store, clock: Clock, ids: IdSource) -> None:
        self._store = store
        self._clock = clock
        self._ids = ids

    # --- mutations ------------------------------------------------------

    def init(self) -> Outcome:
        raise NotImplementedError

    def add(
        self,
        title: str,
        *,
        body: str = "",
        kind: Kind = Kind.TASK,
        project: ProjectId | None = None,
        priority: int | None = None,
        blocked_by: Sequence[TicketId] = (),
        tags: Sequence[str] = (),
        stage: Stage = Stage.DEVELOPMENT,
    ) -> Outcome:
        """Mints a ticket id, then transacts AddOp. Retries with a fresh id on DUPLICATE_ID."""
        raise NotImplementedError

    def update(self, ticket_id: TicketId, **fields: object) -> Outcome:
        raise NotImplementedError

    def claim(self, ticket_id: TicketId, agent: AgentId, ttl: Duration = DEFAULT_TTL) -> Outcome:
        """Mints a claim id, then transacts ClaimOp. The claim id is in the resulting ticket."""
        raise NotImplementedError

    def claim_next(
        self,
        agent: AgentId,
        ttl: Duration = DEFAULT_TTL,
        *,
        project: ProjectId | None = None,
        kind: Kind | None = None,
        stage: Stage | None = None,
    ) -> Outcome:
        raise NotImplementedError

    def renew(self, ticket_id: TicketId, claim_id: ClaimId, ttl: Duration = DEFAULT_TTL) -> Outcome:
        raise NotImplementedError

    def release(
        self,
        ticket_id: TicketId,
        claim_id: ClaimId,
        reason: str = "",
        *,
        to_stage: Stage | None = None,
    ) -> Outcome:
        """Release the claim; `to_stage` hands the ticket to another phase (non-terminal)."""
        raise NotImplementedError

    def done(self, ticket_id: TicketId, claim_id: ClaimId) -> Outcome:
        """Complete the ticket (terminal DONE). Holder-only."""
        raise NotImplementedError

    def cancel(self, ticket_id: TicketId, reason: str = "") -> Outcome:
        """Abandon the ticket (terminal CANCELLED). Administrative; needs no claim."""
        raise NotImplementedError

    def reap(self) -> Outcome:
        raise NotImplementedError

    # --- reads ----------------------------------------------------------

    def snapshot(self) -> Snapshot:
        return self._store.snapshot()

    def get(self, ticket_id: TicketId) -> Ticket | None:
        raise NotImplementedError

    def status(self, ticket_id: TicketId) -> Status | None:
        raise NotImplementedError

    def list(
        self,
        *,
        status: Status | None = None,
        stage: Stage | None = None,
        project: ProjectId | None = None,
        agent: AgentId | None = None,
        kind: Kind | None = None,
    ) -> Sequence[Ticket]:
        raise NotImplementedError

    def claim_of(self, ticket_id: TicketId) -> Claim | None:
        raise NotImplementedError

    def log(
        self, ticket_id: TicketId | None = None, limit: int | None = None
    ) -> Sequence[HistoryEntry]:
        raise NotImplementedError


def raise_for_refusal(outcome: Outcome) -> Outcome:
    """Return `outcome` unless it is Refused, in which case raise RefusedError."""
    if isinstance(outcome, Refused):
        raise RefusedError(outcome.refusal)
    return outcome
