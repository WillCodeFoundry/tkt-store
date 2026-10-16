"""What a decision produces: a refusal, a no-op, or a set of changes to persist.

PURE module. `rules.decide` returns one of these. A Refusal is an ordinary
result, not an exception: the rules looked at the facts and said no, which is a
normal part of operation. The infrastructure turns an `Apply` into exactly one
commit; `WriteTicket`, `WriteClaim` and `OpRecord` describe that commit without naming
git.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from tkt_store.domain.operations import OpName
from tkt_store.domain.ticket import (
    AgentId,
    Claim,
    ClaimFile,
    ClaimHash,
    Phase,
    Ticket,
    TicketId,
    Timestamp,
)


class RefusalCode(StrEnum):
    NOT_INITIALISED = "NOT_INITIALISED"
    NOT_FOUND = "NOT_FOUND"
    # add with an existing id: different kind/project, or different content while never
    # edited (content_version 1)
    DUPLICATE_ID = "DUPLICATE_ID"
    # a claim not yet takeable (live or in grace), or the claim id is already another
    # ticket's or another agent's current claim
    ALREADY_CLAIMED = "ALREADY_CLAIMED"
    NOT_HOLDER = (
        "NOT_HOLDER"  # fencing: not the current claim, an ended claim id, or done by another
    )
    NOT_CLAIMED = "NOT_CLAIMED"
    BLOCKED = "BLOCKED"  # a blocker is not yet done
    TERMINAL = "TERMINAL"  # the ticket is already resolved (done/cancelled): final
    NOTHING_CLAIMABLE = "NOTHING_CLAIMABLE"  # claim-next found no candidate
    # malformed op: bad id, a field rule (domain/fields.py), ttl out of bounds,
    # expected_version < 1, unknown/self blocker, dependency cycle; or the ticket it would
    # write breaks a field rule or exceeds the file cap
    INVALID = "INVALID"
    STALE = "STALE"  # edit based on an older content_version; re-read and retry
    # the op names a ticket or claim set aside on reading (ADR 0005, ADR 0007), or a
    # ticket held by a set-aside claim: an operator must repair the store
    SET_ASIDE = "SET_ASIDE"


@dataclass(frozen=True)
class Refusal:
    """The rules declined the op. Expected; carried as a value, never raised in the core."""

    code: RefusalCode
    message: str


@dataclass(frozen=True)
class WriteTicket:
    """Persist this ticket (create or replace its file)."""

    ticket: Ticket


@dataclass(frozen=True)
class WriteClaim:
    """Persist this claim's file, replacing `replaces` (the same claim, in its state before
    this op): a renewal or an end is a rename. Claim files are never deleted."""

    claim: ClaimFile
    replaces: Claim | None = None


Change = WriteTicket | WriteClaim
"""Tickets and claims are never deleted (design.md Q1, ADR 0007)."""


@dataclass(frozen=True)
class OpRecord:
    """The audit entry for one applied op, written as commit trailers (docs/format.md).

    `at` is the injected `now` the decision was made at (set by the rules), so the
    audit time is deterministic and needs no clock in the store. Clocks may skew
    across writers: `at` is informational and never grants exclusivity.
    `phase` is the new phase on a `move` (`tkt-phase`).
    """

    op: OpName
    at: Timestamp
    ticket_ids: tuple[TicketId, ...] = ()
    agent: AgentId | None = None
    claim_hash: ClaimHash | None = None
    reason: str = ""
    summary: str = ""
    phase: Phase | None = None


@dataclass(frozen=True)
class Apply:
    """The op changes the store: persist these changes together under this record."""

    changes: Sequence[Change]
    record: OpRecord


@dataclass(frozen=True)
class NoOp:
    """The op's effect is already present (invariant 5: idempotence). Nothing to persist.

    `ticket_ids` names the tickets the op concerns (e.g. the ticket a re-run of
    claim-next already holds), so the caller still learns which ticket and claim it has.
    """

    reason: str
    ticket_ids: tuple[TicketId, ...] = ()


Decision = Apply | NoOp | Refusal
