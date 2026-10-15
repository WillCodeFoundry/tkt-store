"""Operations: the changes a caller can request, each carrying its own identity.

PURE module. Invariant 7 (carried identity): ticket ids and claim ids are
minted by the caller BEFORE the transaction, so a retried or re-run op reuses
them and converges instead of duplicating.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tkt_store.domain.ticket import AgentId, ClaimId, Duration, Kind, ProjectId, Stage, TicketId


class OpName(StrEnum):
    """The stable name of each operation, written into the audit record."""

    INIT = "init"
    ADD = "add"
    UPDATE = "update"
    CLAIM = "claim"
    CLAIM_NEXT = "claim-next"
    RENEW = "renew"
    RELEASE = "release"
    DONE = "done"
    CANCEL = "cancel"
    REAP = "reap"


@dataclass(frozen=True)
class InitOp:
    """Create the store ref with an empty tickets/ tree. A no-op if it exists."""


@dataclass(frozen=True)
class AddOp:
    ticket_id: TicketId  # minted by the caller; a repeat with identical content is a no-op
    title: str
    body: str = ""
    kind: Kind = Kind.TASK
    project: ProjectId | None = None
    priority: int | None = None
    blocked_by: tuple[TicketId, ...] = ()
    tags: tuple[str, ...] = ()
    stage: Stage = Stage.DEVELOPMENT  # the phase a new ticket starts in
    agent: AgentId | None = None  # who acted, for the audit record (tkt-agent)


@dataclass(frozen=True)
class UpdateOp:
    """Edit descriptive fields. None means 'leave unchanged'. Never touches claim/stage."""

    ticket_id: TicketId
    title: str | None = None
    body: str | None = None
    priority: int | None = None
    blocked_by: tuple[TicketId, ...] | None = None
    tags: tuple[str, ...] | None = None
    agent: AgentId | None = None  # who acted, for the audit record (tkt-agent)


@dataclass(frozen=True)
class ClaimOp:
    ticket_id: TicketId
    agent: AgentId
    claim_id: ClaimId  # minted by the caller
    ttl: Duration


@dataclass(frozen=True)
class ClaimNextOp:
    """Atomically choose and claim the most urgent claimable ticket matching the filters."""

    agent: AgentId
    claim_id: ClaimId
    ttl: Duration
    project: ProjectId | None = None
    kind: Kind | None = None
    stage: Stage | None = None  # e.g. a review agent pulls only stage=review


@dataclass(frozen=True)
class RenewOp:
    ticket_id: TicketId
    claim_id: ClaimId
    ttl: Duration


@dataclass(frozen=True)
class ReleaseOp:
    """Give up a claim. `to_stage`, if set, hands the ticket on to another phase
    (a non-terminal stage) in the same commit. Use DoneOp/CancelOp to finish."""

    ticket_id: TicketId
    claim_id: ClaimId
    reason: str = ""
    to_stage: Stage | None = None


@dataclass(frozen=True)
class DoneOp:
    """Complete the ticket: move it to the terminal DONE stage. Holder-only."""

    ticket_id: TicketId
    claim_id: ClaimId


@dataclass(frozen=True)
class CancelOp:
    """Abandon the ticket: move it to the terminal CANCELLED stage.
    Requires no claim (an administrative act)."""

    ticket_id: TicketId
    reason: str = ""
    agent: AgentId | None = None  # who acted, for the audit record (tkt-agent)


@dataclass(frozen=True)
class ReapOp:
    """Release every expired claim. Not scoped to one ticket."""


Op = (
    InitOp
    | AddOp
    | UpdateOp
    | ClaimOp
    | ClaimNextOp
    | RenewOp
    | ReleaseOp
    | DoneOp
    | CancelOp
    | ReapOp
)
