"""The value types: tickets, claims, and the identities that name them.

PURE module. No IO, no git, no clock reads, no randomness. It imports nothing from
the package; only the standard library.
Status is NOT here — it is derived in `domain.status`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, NewType

TicketId = NewType("TicketId", str)
AgentId = NewType("AgentId", str)
ClaimId = NewType("ClaimId", str)
ProjectId = NewType("ProjectId", str)

TICKET_PREFIX = "tkt-"
TICKET_ID_RE = re.compile(rf"^{TICKET_PREFIX}[0-9a-f]+$")
"""A ticket id, also its file name `tickets/<id>.json`: no '/', '.', or traversal."""

CLAIM_ID_RE = re.compile(r"^[0-9a-f]{32}$")
"""A claim id: exactly 128 bits as lowercase hex. Written into the `tkt-claim` trailer."""

Revision = NewType("Revision", str)
"""An opaque handle to one committed state of the store.

Backed by a git commit id today, but callers treat it as an opaque token: the
only thing anyone does with a Revision is read it from a snapshot and hand it
back as the `base` of a commit (compare-and-swap). Never parsed, never ordered.
"""

Timestamp = int
"""Unix seconds. Always produced by an injected clock, never read in this layer."""

Duration = int
"""A length of time in whole seconds (e.g. a lease TTL). Non-negative."""

SKEW_GRACE: Duration = 60
"""Seconds past `lease_until` before a lapsed claim may be ACTED on (taken over or
reaped). Absorbs clock skew between writers so a fast-clocked writer cannot take a
claim its holder still considers live. A fixed v1 constant, not per-store."""

MAX_TTL: Duration = 24 * 60 * 60
"""Upper bound on a lease TTL (claim, claim-next, renew). Without it a huge TTL would be
a permanent lock that neither reap nor takeover can clear."""


class Kind(StrEnum):
    STORY = "story"
    TASK = "task"
    BUG = "bug"


class Stage(StrEnum):
    """Where a ticket sits in its lifecycle. A single stored field (ADR 0004).

    The non-terminal values are the workflow vocabulary — the phases a ticket is
    handed through. They carry no forced order: a holder may move a ticket to any
    of them (forward, or back to `DEVELOPMENT` for rework). The two terminal
    values are a one-way latch: a terminal ticket is finished and leaves the
    workable pool for good.
    """

    # workflow (non-terminal)
    DEVELOPMENT = "development"  # the initial stage of a new ticket
    REVIEW = "review"
    QA = "qa"
    # terminal
    DONE = "done"  # completed by its holder
    CANCELLED = "cancelled"  # abandoned (an administrative act)


TERMINAL: frozenset[Stage] = frozenset({Stage.DONE, Stage.CANCELLED})
"""The finished stages. `stage in TERMINAL` is the finality latch."""


@dataclass(frozen=True)
class Claim:
    """An exclusive, time-limited hold on a ticket (ADR 0003).

    The lease is advisory; the `claim_id` is authoritative (fencing). A lapsed
    claim may still be renewed, released or completed by its holder until someone
    takes it over or reaps it.
    """

    agent: AgentId
    claim_id: ClaimId
    lease_until: Timestamp
    claimed_at: Timestamp
    """When this claim was taken (the claimant's injected clock); renew keeps it."""

    def age(self, now: Timestamp) -> Duration:
        """Seconds since `claimed_at` (claim age, shown by `tkt show`). Informational:
        clocks may skew across writers."""
        raise NotImplementedError

    def is_live(self, now: Timestamp) -> bool:
        """True while the lease has not expired (now < lease_until)."""
        raise NotImplementedError

    def is_takeable(self, now: Timestamp) -> bool:
        """True once the claim may be acted on as expired — taken over or reaped:
        now >= lease_until + SKEW_GRACE. Display (Status.EXPIRED) starts earlier, at
        lease_until."""
        raise NotImplementedError


@dataclass(frozen=True)
class Ticket:
    """One unit of work. Mirrors tickets/<id>.json (docs/format.md)."""

    id: TicketId
    title: str
    created: Timestamp
    updated: Timestamp
    """Set to `now` by every op that writes this ticket."""
    version: int = 1
    """Content version for optimistic concurrency: 1 when added, incremented only by
    `update` (the fields it can change). Claims, renewals, handoffs and other ops do not
    touch it, so an active holder's renewals never make an editor's update STALE.
    `update` must name the version it was based on."""
    body: str = ""
    kind: Kind = Kind.TASK
    project: ProjectId | None = None
    priority: int | None = None
    blocked_by: tuple[TicketId, ...] = ()
    tags: tuple[str, ...] = ()
    claim: Claim | None = None
    stage: Stage = Stage.DEVELOPMENT
    done_by: ClaimId | None = None
    """The claim that completed the ticket; set only when stage is DONE. Keeps `done`
    fenced after completion (a repeat is a NoOp only for this claim id)."""
    last_claim_id: ClaimId | None = None
    """The most recent claim that ended other than by `done`: released, reaped, taken
    over, or cleared by cancel. Fences that id (it cannot claim again) and makes a
    release re-run converge."""
    extra: Mapping[str, Any] = field(default_factory=dict)
    """Unknown keys from the file, preserved verbatim on write-back."""

    @property
    def is_terminal(self) -> bool:
        """True once the ticket is done or cancelled (the finality latch)."""
        return self.stage in TERMINAL

    @property
    def is_done(self) -> bool:
        """True only when completed. A cancelled ticket is terminal but not done,
        so it does NOT satisfy a dependency (invariant 10)."""
        return self.stage is Stage.DONE


@dataclass(frozen=True)
class Snapshot:
    """An immutable view of the store at one revision.

    `revision` is None only for an unborn store (before `init`). It is what a commit
    built from this snapshot passes as its `base` (compare-and-swap).
    """

    revision: Revision | None
    tickets: Mapping[TicketId, Ticket]

    def get(self, ticket_id: TicketId) -> Ticket | None:
        return self.tickets.get(ticket_id)
