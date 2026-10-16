"""TicketStore: the facade agents (directly or via the CLI) use.

Mints ticket ids BEFORE transacting (invariant 7), runs ops through the transaction
loop, and returns its outcomes. Claim ids are never minted here: the caller supplies
them, since only their hash is stored and a minted id could never be read back
(ADR 0005). Owns no rules of its own beyond that wiring. It
depends only on ports (Store, Clock, IdSource); the concrete implementations are
chosen at the composition root (`tkt_store.open_store`), never here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from tkt_store.application.backoff import Backoff
from tkt_store.application.clock import Clock
from tkt_store.application.errors import RefusedError
from tkt_store.application.ids import IdSource
from tkt_store.application.store import HistoryEntry, Store
from tkt_store.application.transaction import Outcome, Refused, transact
from tkt_store.domain.operations import (
    UNSET,
    AddOp,
    CancelOp,
    ClaimNextOp,
    ClaimOp,
    DoneOp,
    EditOp,
    InitOp,
    MoveOp,
    Op,
    ReapOp,
    ReleaseOp,
    RenewOp,
    Unset,
    UnsetType,
)
from tkt_store.domain.outcomes import Refusal, RefusalCode
from tkt_store.domain.rules import ticket_set_aside
from tkt_store.domain.status import Status, derive_status
from tkt_store.domain.ticket import (
    AgentId,
    Claim,
    ClaimId,
    Duration,
    Kind,
    Phase,
    ProjectId,
    Snapshot,
    Ticket,
    TicketId,
)

DEFAULT_TTL: Duration = 30 * 60

MAX_MINT_ATTEMPTS = 10
"""How often `add` re-mints a ticket id that collided with an existing one."""

TAKEN = frozenset({RefusalCode.DUPLICATE_ID, RefusalCode.SET_ASIDE})
"""Refusals that mean a minted ticket id is already taken."""


@dataclass(frozen=True)
class TicketView:
    """A ticket with its open claim and derived status, all taken from the same snapshot."""

    ticket: Ticket
    claim: Claim | None
    status: Status


class TicketStore:
    """All mutating methods return the transaction Outcome. Callers that prefer
    exceptions can wrap a call in `raise_for_refusal`, which raises on a refusal.

    Committed and Unchanged carry the affected tickets, each with its open claim (so a
    re-run still reports the ticket and claim it holds). RetriesExhausted and StoreError
    carry the `op` with the ids it was last tried with: re-run with those ids to converge.

    Construct it with explicit dependencies, or use `tkt_store.open_store(repo)`
    for the production wiring.
    """

    def __init__(
        self, store: Store, clock: Clock, ids: IdSource, *, backoff: Backoff | None = None
    ) -> None:
        """`backoff`: how to wait between lost races; None retries at once (tests).
        `open_store` passes the production JitteredBackoff."""
        self._store = store
        self._clock = clock
        self._ids = ids
        self._backoff = backoff

    # --- mutations ------------------------------------------------------

    def init(self) -> Outcome:
        return self._transact(InitOp())

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
        phase: Phase = Phase.TRIAGE,
        ticket_id: TicketId | None = None,
        agent: AgentId | None = None,
    ) -> Outcome:
        """Transacts AddOp. `agent`, when given, is recorded as the actor.

        `ticket_id` None: mint one from the IdSource; on DUPLICATE_ID or SET_ASIDE re-mint
        and try again (a mint collision with a ticket, or with one set aside; never a
        re-run: a re-run of your own add is a NoOp).
        Supplied: used verbatim (validated by the rules) and the DUPLICATE_ID / NoOp
        outcome is returned without retrying, so a re-run converges. Failures carry the
        op with the last id tried.
        """

        def op(ticket_id: TicketId) -> AddOp:
            return AddOp(
                ticket_id,
                title,
                body=body,
                kind=kind,
                project=project,
                priority=priority,
                blocked_by=tuple(blocked_by),
                tags=tuple(tags),
                phase=phase,
                agent=agent,
            )

        if ticket_id is not None:
            return self._transact(op(ticket_id))
        for _ in range(MAX_MINT_ATTEMPTS):
            outcome = self._transact(op(self._ids.ticket_id()))
            if not (isinstance(outcome, Refused) and outcome.refusal.code in TAKEN):
                return outcome
        return outcome

    def edit(
        self,
        ticket_id: TicketId,
        expected_version: int,
        *,
        title: str | UnsetType = UNSET,
        body: str | UnsetType = UNSET,
        priority: int | UnsetType | None = UNSET,
        blocked_by: Sequence[TicketId] | UnsetType = UNSET,
        tags: Sequence[str] | UnsetType = UNSET,
        agent: AgentId | None = None,
    ) -> Outcome:
        """Transacts EditOp. Omitted fields are unchanged; `priority=None` clears it.
        `expected_version` is the content_version the edit is based on (from `get`); if
        the ticket changed since, the outcome is Refused(STALE): re-read and retry.
        `agent`, when given, is recorded as the actor."""
        return self._transact(
            EditOp(
                ticket_id,
                expected_version,
                title=title,
                body=body,
                priority=priority,
                blocked_by=blocked_by if isinstance(blocked_by, Unset) else tuple(blocked_by),
                tags=tags if isinstance(tags, Unset) else tuple(tags),
                agent=agent,
            )
        )

    def claim(
        self,
        ticket_id: TicketId,
        agent: AgentId,
        ttl: Duration = DEFAULT_TTL,
        *,
        claim_id: ClaimId,
    ) -> Outcome:
        """Transacts ClaimOp. `claim_id` is the caller's (mint it with IdSource.claim_id
        and keep it): only its hash is stored. Re-running with the same id and agent
        converges: NoOp (Unchanged) while the claim is live; if it lapsed and nobody took
        it over, it is renewed (Committed). A claim id is single-use: never reuse one
        whose claim has ended.
        """
        return self._transact(ClaimOp(ticket_id, agent, claim_id, ttl))

    def claim_next(
        self,
        agent: AgentId,
        ttl: Duration = DEFAULT_TTL,
        *,
        project: ProjectId | None = None,
        kind: Kind | None = None,
        phase: Phase | None = None,
        claim_id: ClaimId,
    ) -> Outcome:
        """Transacts ClaimNextOp. `claim_id` as in `claim`: a re-run with the same id
        and agent converges on the ticket it already holds — Unchanged naming it while the
        claim is live, Committed (renewed) if it lapsed — never a second ticket."""
        return self._transact(
            ClaimNextOp(agent, claim_id, ttl, project=project, kind=kind, phase=phase)
        )

    def renew(self, ticket_id: TicketId, claim_id: ClaimId, ttl: Duration = DEFAULT_TTL) -> Outcome:
        return self._transact(RenewOp(ticket_id, claim_id, ttl))

    def move(self, ticket_id: TicketId, claim_id: ClaimId, to_phase: Phase) -> Outcome:
        """Move the ticket to `to_phase`, keeping the claim (holder only). A handoff is
        move, then release."""
        return self._transact(MoveOp(ticket_id, claim_id, to_phase))

    def release(self, ticket_id: TicketId, claim_id: ClaimId, reason: str = "") -> Outcome:
        """Release the claim (holder only); the phase is untouched."""
        return self._transact(ReleaseOp(ticket_id, claim_id, reason))

    def done(self, ticket_id: TicketId, claim_id: ClaimId) -> Outcome:
        """Complete the ticket (terminal DONE). Holder-only."""
        return self._transact(DoneOp(ticket_id, claim_id))

    def cancel(
        self, ticket_id: TicketId, reason: str = "", *, agent: AgentId | None = None
    ) -> Outcome:
        """Abandon the ticket (terminal CANCELLED). Administrative; needs no claim.
        `agent`, when given, is recorded as the actor."""
        return self._transact(CancelOp(ticket_id, reason, agent))

    def reap(self) -> Outcome:
        return self._transact(ReapOp())

    def _transact(self, op: Op) -> Outcome:
        return transact(self._store, op, self._clock, backoff=self._backoff)

    # --- reads ----------------------------------------------------------

    def snapshot(self) -> Snapshot:
        return self._store.snapshot()

    def get(self, ticket_id: TicketId) -> Ticket | None:
        return self._store.snapshot().get(ticket_id)

    def view(self, ticket_id: TicketId) -> TicketView | None:
        """The ticket and its derived status, from ONE snapshot (so they always agree);
        None if it does not exist."""
        snapshot = self._store.snapshot()
        ticket = snapshot.get(ticket_id)
        if ticket is None:
            return None
        status = derive_status(snapshot, ticket, self._clock.now())
        return TicketView(ticket, snapshot.claim_of(ticket_id), status)

    def show(self, ticket_id: TicketId) -> TicketView | Refused:
        """`view`, or the refusal for an id with no valid ticket: SET_ASIDE if its file was
        set aside on reading (naming the check that failed), else NOT_FOUND."""
        snapshot = self._store.snapshot()
        if (aside := ticket_set_aside(snapshot, ticket_id)) is not None:
            return Refused(aside)
        ticket = snapshot.get(ticket_id)
        if ticket is None:
            return Refused(Refusal(RefusalCode.NOT_FOUND, f"no ticket {ticket_id}"))
        status = derive_status(snapshot, ticket, self._clock.now())
        return TicketView(ticket, snapshot.claim_of(ticket_id), status)

    def list(
        self,
        *,
        status: Status | None = None,
        phase: Phase | None = None,
        project: ProjectId | None = None,
        agent: AgentId | None = None,
        kind: Kind | None = None,
    ) -> Sequence[TicketView]:
        """Matching tickets with their derived status, all from one snapshot."""
        snapshot = self._store.snapshot()
        now = self._clock.now()
        views = []
        for ticket in sorted(snapshot.tickets.values(), key=lambda t: t.id):
            claim = snapshot.claim_of(ticket.id)
            view = TicketView(ticket, claim, derive_status(snapshot, ticket, now))
            if (
                (status is None or view.status is status)
                and (phase is None or ticket.phase is phase)
                and (project is None or ticket.project == project)
                and (agent is None or (claim is not None and claim.agent == agent))
                and (kind is None or ticket.kind is kind)
            ):
                views.append(view)
        return views

    def log(
        self, ticket_id: TicketId | None = None, limit: int | None = None
    ) -> Sequence[HistoryEntry]:
        return list(self._store.history(ticket_id, limit))


def raise_for_refusal(outcome: Outcome) -> Outcome:
    """Return `outcome` unless it is Refused, in which case raise RefusedError."""
    if isinstance(outcome, Refused):
        raise RefusedError(outcome.refusal)
    return outcome
