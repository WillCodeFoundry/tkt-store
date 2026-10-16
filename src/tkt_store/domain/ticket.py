"""The value types: tickets, claims, and the identities that name them.

PURE module. No IO, no git, no clock reads, no randomness. It imports nothing from
the package; only the standard library.
Status is NOT here — it is derived in `domain.status`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import cached_property
from types import MappingProxyType
from typing import Any, NewType

TicketId = NewType("TicketId", str)
AgentId = NewType("AgentId", str)
ClaimId = NewType("ClaimId", str)
ProjectId = NewType("ProjectId", str)

TICKET_PREFIX = "tkt-"
"""The prefix of minted ids (`tkt-` + 8 hex digits); a caller's own id needs none."""
TICKET_ID_RE = re.compile(r"(?=[a-z0-9-]{8,32}\Z)[a-z0-9]+(?:-[a-z0-9]+)*")
"""A ticket id, also its file name `tickets/<id>.json`: 8 to 32 lowercase letters, digits
and single hyphens, starting and ending with a letter or digit (e.g. `tkt-7f3a91c2`,
`fix-login-redirect`); no '/', '.', or traversal. Always check with `fullmatch` (never
`match` with `$`, which accepts a trailing newline)."""

CLAIM_ID_RE = re.compile(r"[0-9a-f]{32}")
"""A claim id: exactly 128 bits as lowercase hex, supplied by the caller and never stored:
only its hash is (`claim_hash`). Always check with `fullmatch`."""

ClaimHash = NewType("ClaimHash", str)
CLAIM_HASH_RE = re.compile(r"[0-9a-f]{64}")
"""A claim's hash: the SHA-256 of its claim id, 64 lowercase hex. It names the claim's
file and fills the `tkt-claim` trailer (ADR 0005, ADR 0007). Check with `fullmatch`."""


def claim_hash(claim_id: ClaimId) -> ClaimHash:
    """The stored form of a claim id. Only the agent that minted the id can produce it."""
    return ClaimHash(hashlib.sha256(claim_id.encode()).hexdigest())


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

LEASE_CAP_MARGIN: Duration = 10 * 60
"""How far a writer's clock may run ahead before its longest lease looks forged: a lease
ending more than MAX_TTL + LEASE_CAP_MARGIN after now is beyond the cap
(`Claim.is_beyond_cap`). Generous for clocks kept in time; a forged lease can lock a
ticket for at most that long."""


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


class EndedBy(StrEnum):
    """How a claim ended (ADR 0007): part of its file name once it has."""

    RELEASED = "released"  # its holder gave it back
    DONE = "done"  # its holder completed the ticket
    CANCELLED = "cancelled"  # the ticket was cancelled while it was held
    REAPED = "reaped"  # reap cleared it, past its lease and the grace
    TAKEN_OVER = "taken-over"  # a new claim took the ticket, past its lease and the grace
    REVOKED = "revoked"  # stage 4: ended by anyone without resolving the ticket


@dataclass(frozen=True)
class Claim:
    """An open, exclusive, time-limited hold on a ticket (ADR 0003, ADR 0007).

    Stored as an empty file whose name is its whole state:
    `claims/<ticket_id>/<hash>.open.<agent>.<claimed_at>.<lease_until>`. The lease is
    advisory; the hash is authoritative (fencing). A lapsed claim may still be renewed,
    released or completed by its holder until someone takes it over or reaps it.
    """

    ticket_id: TicketId
    hash: ClaimHash
    agent: AgentId
    claimed_at: Timestamp
    """When this claim was taken (the claimant's injected clock); renew keeps it."""
    lease_until: Timestamp

    def age(self, now: Timestamp) -> Duration:
        """Seconds since `claimed_at` (claim age, shown by `tkt show`), never negative.
        Informational: clocks may skew across writers."""
        return max(0, now - self.claimed_at)

    def is_live(self, now: Timestamp) -> bool:
        """True while the lease has not expired (now < lease_until) and is not beyond
        the cap (`is_beyond_cap`)."""
        return now < self.lease_until and not self.is_beyond_cap(now)

    def is_takeable(self, now: Timestamp) -> bool:
        """True once the claim may be acted on as expired — taken over or reaped:
        now >= lease_until + SKEW_GRACE, or a lease beyond the cap. Display
        (Status.EXPIRED) starts earlier, at lease_until."""
        return now >= self.lease_until + SKEW_GRACE or self.is_beyond_cap(now)

    def is_beyond_cap(self, now: Timestamp) -> bool:
        """A lease ending more than MAX_TTL + LEASE_CAP_MARGIN after now, which no honest
        writer sets (claim and renew cap it at the writer's now + MAX_TTL, and clocks
        agree within the margin). Such a claim reads expired and is takeable, so a forged
        lease cannot lock a ticket. The cap is relative to now, never to claimed_at, so an
        honestly renewed claim is never beyond it."""
        return self.lease_until > now + MAX_TTL + LEASE_CAP_MARGIN

    def renewed(self, lease_until: Timestamp) -> Claim:
        """This claim with a new lease, never before `claimed_at`: a renewer whose clock
        is behind the claimer's still writes a name it would accept (ADR 0007)."""
        return replace(self, lease_until=max(lease_until, self.claimed_at))

    def ended(self, by: EndedBy, at: Timestamp) -> EndedClaim:
        """This claim, ended `by` at `at`, never before `claimed_at` (as `renewed`)."""
        return EndedClaim(
            self.ticket_id, self.hash, self.agent, self.claimed_at, by, max(at, self.claimed_at)
        )

    def to_dict(self) -> dict[str, Any]:
        """The claim as plain data, as interfaces print it: the hash, never a claim id."""
        return {
            "claim_hash": self.hash,
            "agent": self.agent,
            "claimed_at": self.claimed_at,
            "lease_until": self.lease_until,
        }


@dataclass(frozen=True)
class EndedClaim:
    """A claim that has ended, kept for good so its hash stays fenced (it can never claim
    again) and re-runs of holder ops converge. Stored as an empty file:
    `claims/<ticket_id>/<hash>.<ended_by>.<agent>.<claimed_at>.<ended_at>`."""

    ticket_id: TicketId
    hash: ClaimHash
    agent: AgentId
    claimed_at: Timestamp
    ended_by: EndedBy
    ended_at: Timestamp

    def to_dict(self) -> dict[str, Any]:
        """The ended claim as plain data, as interfaces print it."""
        return {
            "claim_hash": self.hash,
            "agent": self.agent,
            "claimed_at": self.claimed_at,
            "ended_by": self.ended_by.value,
            "ended_at": self.ended_at,
        }


ClaimFile = Claim | EndedClaim
"""What one claim file holds: an open claim or an ended one."""


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
    - bookkeeping  updated — maintained by the system

    Occupancy is not here: claims are files of their own (`Claim`, `EndedClaim`;
    ADR 0007), held in the snapshot next to the tickets.
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

    # --- bookkeeping: maintained by the system
    updated: Timestamp
    """Set to `now` by every op that writes this ticket: add, edit, move, done, cancel.
    Claim ops do not write the ticket, so they leave it alone."""

    @property
    def is_terminal(self) -> bool:
        """True once the ticket is resolved (done or cancelled): the finality latch."""
        return self.resolution is not None

    @property
    def is_done(self) -> bool:
        """True only when completed. A cancelled ticket is terminal but not done,
        so it does NOT satisfy a dependency (invariant 10)."""
        return self.resolution is Resolution.DONE

    def to_dict(self) -> dict[str, Any]:
        """The ticket as plain data. This IS the on-branch ticket format (docs/format.md):
        a change here is a format change, under the protocol-version rule in AGENTS.md.
        Interfaces print it too."""
        return {
            "id": self.id,
            "kind": self.kind.value,
            "project": self.project,
            "created": self.created,
            "title": self.title,
            "body": self.body,
            "priority": self.priority,
            "blocked_by": list(self.blocked_by),
            "tags": list(self.tags),
            "content_version": self.content_version,
            "phase": self.phase.value,
            "resolution": None if self.resolution is None else self.resolution.value,
            "updated": self.updated,
        }

    def encoded(self) -> bytes:
        """The ticket file's bytes: `to_dict` in the canonical encoding."""
        return canonical_json(self.to_dict())


def canonical_json(value: object) -> bytes:
    """The on-branch file encoding (docs/format.md): UTF-8 JSON, sorted keys, 2-space
    indent, trailing newline. Stable diffs and byte-identical round trips."""
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


@dataclass(frozen=True)
class TicketState:
    """A ticket with its valid open claim, as one snapshot sees it."""

    ticket: Ticket
    claim: Claim | None = None


_EMPTY: Mapping[Any, Any] = MappingProxyType({})


@dataclass(frozen=True)
class Snapshot:
    """An immutable view of the store at one revision: the valid tickets and claims, and
    what was set aside on reading (ADR 0005, ADR 0007), which the rules never act on.

    `revision` is None only for an unborn store (before `init`). It is what a commit
    built from this snapshot passes as its `base` (compare-and-swap).
    """

    revision: Revision | None
    tickets: Mapping[TicketId, Ticket]
    claims: Mapping[TicketId, Claim] = _EMPTY
    """The valid open claim of each held ticket."""
    ended: Mapping[ClaimHash, EndedClaim] = _EMPTY
    """Every valid ended claim, by hash."""
    set_aside: Mapping[TicketId, str] = _EMPTY
    """Ticket ids set aside, with the check that failed: an invalid ticket file, or a
    claims folder with no ticket. No op may act on them (`SET_ASIDE`)."""
    held_aside: Mapping[TicketId, str] = _EMPTY
    """Valid tickets held by a set-aside claim: only `cancel` may act on them."""
    fenced: Mapping[ClaimHash, str] = _EMPTY
    """Hashes with no valid claim file but a set-aside one, or whose claim lies on a
    set-aside ticket: they fence (never claim again) but can't be acted on."""

    def get(self, ticket_id: TicketId) -> Ticket | None:
        return self.tickets.get(ticket_id)

    def claim_of(self, ticket_id: TicketId) -> Claim | None:
        """The ticket's valid open claim, if it is held by one."""
        return self.claims.get(ticket_id)

    def state(self, ticket_id: TicketId) -> TicketState | None:
        """The ticket with its open claim, or None if there is no such valid ticket."""
        ticket = self.tickets.get(ticket_id)
        return None if ticket is None else TicketState(ticket, self.claims.get(ticket_id))

    def find(self, claim_hash: ClaimHash) -> ClaimFile | None:
        """The valid claim, open or ended, with this hash anywhere in the store."""
        return self._open_by_hash.get(claim_hash) or self.ended.get(claim_hash)

    @cached_property
    def _open_by_hash(self) -> Mapping[ClaimHash, Claim]:
        return {claim.hash: claim for claim in self.claims.values()}
