"""Operations: the changes a caller can request, each carrying its own identity.

PURE module. Invariant 7 (carried identity): ticket ids and claim ids are
minted by the caller BEFORE the transaction, so a retried or re-run op reuses
them and converges instead of duplicating.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Final, Literal

from tkt_store.domain.ticket import AgentId, ClaimId, Duration, Kind, Phase, ProjectId, TicketId


class Unset(Enum):
    """'Leave this field unchanged' in an edit, distinct from None ('clear it').
    A plain Enum, not a StrEnum: it must never compare equal to a real string value."""

    UNSET = "unset"


UNSET: Final = Unset.UNSET
UnsetType = Literal[Unset.UNSET]


class OpName(StrEnum):
    """The stable name of each operation, written into the audit record."""

    INIT = "init"
    ADD = "add"
    EDIT = "edit"
    CLAIM = "claim"
    CLAIM_NEXT = "claim-next"
    RENEW = "renew"
    MOVE = "move"
    RELEASE = "release"
    DONE = "done"
    CANCEL = "cancel"
    REAP = "reap"


@dataclass(frozen=True)
class InitOp:
    """Create the store ref with an empty tickets/ tree (the git store also writes
    tkt-store.json). A no-op if it exists."""


@dataclass(frozen=True)
class AddOp:
    ticket_id: TicketId  # minted by the caller; a re-run is a no-op (see decide_add)
    title: str
    body: str = ""
    kind: Kind = Kind.TASK
    project: ProjectId | None = None
    priority: int | None = None
    blocked_by: tuple[TicketId, ...] = ()
    tags: tuple[str, ...] = ()
    phase: Phase = Phase.TRIAGE  # the phase a new ticket starts in
    agent: AgentId | None = None  # who acted, for the audit record (tkt-agent)


@dataclass(frozen=True)
class EditOp:
    """Edit descriptive fields. UNSET means 'leave unchanged'; `priority=None` clears it.
    Changes content fields only (never identity, workflow or occupancy).

    `expected_version` is required: the content_version the edit was based on. A ticket
    changed since then is refused STALE instead of silently overwritten.
    """

    ticket_id: TicketId
    expected_version: int
    title: str | UnsetType = UNSET
    body: str | UnsetType = UNSET
    priority: int | UnsetType | None = UNSET
    blocked_by: tuple[TicketId, ...] | UnsetType = UNSET
    tags: tuple[str, ...] | UnsetType = UNSET
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
    phase: Phase | None = None  # e.g. a review agent pulls only phase=review


@dataclass(frozen=True)
class RenewOp:
    ticket_id: TicketId
    claim_id: ClaimId
    ttl: Duration


@dataclass(frozen=True)
class ReleaseOp:
    """Give up a claim (occupancy only; the phase is untouched). A handoff is MoveOp
    then ReleaseOp. Finishing is DoneOp/CancelOp (they set the resolution)."""

    ticket_id: TicketId
    claim_id: ClaimId
    reason: str = ""


@dataclass(frozen=True)
class MoveOp:
    """Move the ticket to another phase (workflow only). Holder-only; the claim is kept,
    so a handoff (move, then release) never leaves the ticket unheld in the old phase."""

    ticket_id: TicketId
    claim_id: ClaimId
    to_phase: Phase


@dataclass(frozen=True)
class DoneOp:
    """Complete the ticket: resolution = DONE (terminal). Holder-only."""

    ticket_id: TicketId
    claim_id: ClaimId


@dataclass(frozen=True)
class CancelOp:
    """Abandon the ticket: resolution = CANCELLED (terminal).
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
    | EditOp
    | ClaimOp
    | ClaimNextOp
    | RenewOp
    | MoveOp
    | ReleaseOp
    | DoneOp
    | CancelOp
    | ReapOp
)
