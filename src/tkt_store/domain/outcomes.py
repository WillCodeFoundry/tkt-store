"""What a decision produces: a refusal, a no-op, or a set of changes to persist.

PURE module. `rules.decide` returns one of these. A Refusal is an ordinary
result, not an exception: the rules looked at the facts and said no, which is a
normal part of operation. The infrastructure turns an `Apply` into exactly one
commit; `WriteTicket` and `OpRecord` describe that commit without naming git.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from tkt_store.domain.operations import OpName
from tkt_store.domain.ticket import AgentId, ClaimId, Stage, Ticket, TicketId, Timestamp


class RefusalCode(StrEnum):
    NOT_INITIALISED = "NOT_INITIALISED"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE_ID = "DUPLICATE_ID"  # add with an existing id but different content
    ALREADY_CLAIMED = "ALREADY_CLAIMED"  # a live claim held by someone else
    NOT_HOLDER = "NOT_HOLDER"  # claim_id does not match the current claim (fencing)
    NOT_CLAIMED = "NOT_CLAIMED"
    BLOCKED = "BLOCKED"  # a blocker is not yet done
    TERMINAL = "TERMINAL"  # the ticket is already in a terminal stage (done/cancelled)
    NOTHING_CLAIMABLE = "NOTHING_CLAIMABLE"  # claim-next found no candidate
    INVALID = "INVALID"  # malformed op (empty title, bad ttl, bad blocker, terminal to_stage)


@dataclass(frozen=True)
class Refusal:
    """The rules declined the op. Expected; carried as a value, never raised in the core."""

    code: RefusalCode
    message: str


@dataclass(frozen=True)
class WriteTicket:
    """Persist this ticket (create or replace its file)."""

    ticket: Ticket


Change = WriteTicket
"""The only change for now. Tickets are never deleted (design.md Q1)."""


@dataclass(frozen=True)
class OpRecord:
    """The audit entry for one applied op, written as commit trailers (docs/format.md).

    `at` is the injected `now` the decision was made at (set by the rules), so the
    audit time is deterministic and needs no clock in the store. Clocks may skew
    across writers: `at` is informational and never grants exclusivity.
    `stage` is the new stage on a release that hands off (`tkt-stage`).
    """

    op: OpName
    at: Timestamp
    ticket_ids: tuple[TicketId, ...] = ()
    agent: AgentId | None = None
    claim_id: ClaimId | None = None
    reason: str = ""
    summary: str = ""
    stage: Stage | None = None


@dataclass(frozen=True)
class Apply:
    """The op changes the store: persist these changes together under this record."""

    changes: Sequence[Change]
    record: OpRecord


@dataclass(frozen=True)
class NoOp:
    """The op's effect is already present (invariant 5: idempotence). Nothing to persist."""

    reason: str


Decision = Apply | NoOp | Refusal
