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
TICKET_ID_RE = re.compile(rf"{TICKET_PREFIX}[0-9a-f]+")
"""A ticket id, also its file name `tickets/<id>.json`: no '/', '.', or traversal.
Always check with `fullmatch` (never `match` with `$`, which accepts a trailing newline)."""

CLAIM_ID_RE = re.compile(r"[0-9a-f]{32}")
"""A claim id: exactly 128 bits as lowercase hex. Written into the `tkt-claim` trailer.
Always check with `fullmatch`."""

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

MAX_TTL: Duration = 2 * 60 * 60
"""Upper bound on a lease TTL (claim, claim-next, renew). Without it a huge TTL would be
a permanent lock that neither reap nor takeover can clear."""


class Kind(StrEnum):
    STORY = "story"
    TASK = "task"
    BUG = "bug"


class Phase(StrEnum):
    """Where a ticket is in the workflow: which kind of work (or agent role) it waits
    for. `claim-next --phase P` asks for the next ticket for role P.

    A fixed set, named after the roles of swarm-forge's agent packs plus common human
    steps. No forced order: the holder may move a ticket to any phase (forward, or back
    for rework). Changed only by the holder's `move`. Whether the ticket is finished is
    a separate fact: `Resolution`.
    """

    TRIAGE = "triage"  # new or unclear; sort before anyone works on it
    SPECIFICATION = "specification"  # specifier
    IMPLEMENTATION = "implementation"  # coder
    CLEANUP = "cleanup"  # cleaner / refactorer
    ARCHITECTURE = "architecture"  # architect
    HARDENING = "hardening"  # hardener
    QA = "qa"  # QA
    REVIEW = "review"  # human review or approval
    RELEASE = "release"  # deploy, rollout


class Resolution(StrEnum):
    """How a ticket finished. Set once; a resolved ticket is terminal (final)."""

    DONE = "done"  # completed by its holder (`done`)
    CANCELLED = "cancelled"  # abandoned (`cancel`, an administrative act)


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
        """Seconds since `claimed_at` (claim age, shown by `tkt show`), never negative.
        Informational: clocks may skew across writers."""
        return max(0, now - self.claimed_at)

    def is_live(self, now: Timestamp) -> bool:
        """True while the lease has not expired (now < lease_until)."""
        return now < self.lease_until

    def is_takeable(self, now: Timestamp) -> bool:
        """True once the claim may be acted on as expired — taken over or reaped:
        now >= lease_until + SKEW_GRACE. Display (Status.EXPIRED) starts earlier, at
        lease_until."""
        return now >= self.lease_until + SKEW_GRACE


@dataclass(frozen=True, kw_only=True)
class Ticket:
    """One unit of work. Mirrors tickets/<id>.json (docs/format.md).

    Every field belongs to exactly one group, and each group changes one way
    (docs/design.md, "Data model"):

    - identity     id, kind, project, created  — set by `add`, never change
    - content      title, body, priority, blocked_by, tags, content_version
                   — changed only by `edit` (anyone), guarded by content_version
    - workflow     phase, resolution — phase by the holder's `move`; resolution set
                   once by `done` (holder) or `cancel` (anyone)
    - occupancy    claim, ended_claim_ids — changed by claim ops, done, cancel and reap;
                   holder ops (renew/move/release/done) fenced by claim id
    - bookkeeping  updated, extra — maintained by the system
    """

    # --- identity: set by add, never changes
    id: TicketId
    kind: Kind = Kind.TASK
    project: ProjectId | None = None
    created: Timestamp

    # --- content: changed only by edit, guarded by content_version
    title: str
    body: str = ""
    priority: int | None = None
    blocked_by: tuple[TicketId, ...] = ()
    tags: tuple[str, ...] = ()
    content_version: int = 1
    """1 when added, incremented only by `edit`. An edit must name the version it was
    based on (STALE otherwise). Claims, renewals and handoffs never change it."""

    # --- workflow: phase by the holder's move; resolution set once by done/cancel
    phase: Phase = Phase.TRIAGE
    resolution: Resolution | None = None
    """None while open; set once by done/cancel. Non-None means terminal (final)."""

    # --- occupancy: claim ops, done, cancel, reap; holder ops fenced by claim id
    claim: Claim | None = None
    ended_claim_ids: tuple[ClaimId, ...] = ()
    """Every claim that has ended on this ticket, oldest first, however it ended:
    released, reaped, taken over, cancelled, or done. A complete record, so an ended id
    is fenced for good (it can never claim again), re-runs of holder ops converge no
    matter how many claims came since, and refusals can say "your claim already ended".
    With resolution DONE, the last entry is the claim that completed the ticket."""

    # --- bookkeeping: maintained by the system
    updated: Timestamp
    """Set to `now` by every op that writes this ticket."""
    extra: Mapping[str, Any] = field(default_factory=dict)
    """Unknown keys from the file, preserved verbatim on write-back."""

    @property
    def is_terminal(self) -> bool:
        """True once the ticket is resolved (done or cancelled): the finality latch."""
        return self.resolution is not None

    @property
    def is_done(self) -> bool:
        """True only when completed. A cancelled ticket is terminal but not done,
        so it does NOT satisfy a dependency (invariant 10)."""
        return self.resolution is Resolution.DONE


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
