"""Who holds what: the snapshot assembled from tickets and claim files (ADR 0007).

PURE module. A store hands over the valid tickets, the ticket ids it set aside, and
every claim file whose name parsed; `assemble` runs ADR 0007's checks in their fixed
order, so every reader reaches the same verdict:

1. each file: times out of order (which tkt never writes) -> set aside;
2. each hash, over the files that passed step 1: in more than one folder -> every file
   with it set aside; more than one ended file -> all set aside; an open and an ended
   file in one folder -> the ended one wins, the open one is set aside;
3. each folder, over the claims still valid: no ticket -> its claims set aside and the
   id set aside; a set-aside ticket -> its claims fence but can't be acted on; a
   resolved ticket -> every open claim set aside (the resolution wins); more than one
   open claim -> all set aside.

A set-aside claim still fences its hash. A valid ticket is held by a set-aside claim
when an open claim of its folder was set aside in step 1, in step 2 for being in more
than one folder, or in step 3 for being one of several, and the ticket is not resolved.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from tkt_store.domain.outcomes import Change, WriteClaim, WriteTicket
from tkt_store.domain.ticket import (
    Claim,
    ClaimFile,
    ClaimHash,
    EndedClaim,
    Revision,
    Snapshot,
    Ticket,
    TicketId,
)


def assemble(
    revision: Revision | None,
    tickets: Mapping[TicketId, Ticket],
    set_aside: Mapping[TicketId, str],
    claim_files: Iterable[ClaimFile],
) -> Snapshot:
    """The snapshot of `tickets` (all valid) and `claim_files` (every claim file whose
    name parsed), with `set_aside` the ticket ids whose files failed their checks."""
    aside: dict[ClaimFile, str] = {}
    holding: dict[TicketId, str] = {}

    def put_aside(claim: ClaimFile, why: str, *, holds: bool) -> None:
        aside.setdefault(claim, why)
        if holds and isinstance(claim, Claim):
            holding.setdefault(claim.ticket_id, why)

    files = list(dict.fromkeys(claim_files))
    for claim in files:  # step 1
        end = claim.lease_until if isinstance(claim, Claim) else claim.ended_at
        if claim.claimed_at > end:
            put_aside(claim, "a claim's times are out of order", holds=True)

    by_hash: dict[ClaimHash, list[ClaimFile]] = defaultdict(list)
    for claim in files:
        if claim not in aside:
            by_hash[claim.hash].append(claim)
    for same in by_hash.values():  # step 2
        if len({claim.ticket_id for claim in same}) > 1:
            for claim in same:
                put_aside(claim, "a claim hash is in more than one folder", holds=True)
        elif len([c for c in same if isinstance(c, EndedClaim)]) > 1:
            for claim in same:
                put_aside(claim, "a claim has ended more than once", holds=False)
        elif any(isinstance(c, EndedClaim) for c in same):
            for claim in same:
                if isinstance(claim, Claim):
                    put_aside(claim, "a claim is both open and ended", holds=False)

    by_folder: dict[TicketId, list[ClaimFile]] = defaultdict(list)
    for claim in files:
        by_folder[claim.ticket_id].append(claim)
    set_aside = dict(set_aside)
    fenced: dict[ClaimHash, str] = {}
    for ticket_id, folder in by_folder.items():  # step 3
        valid = [claim for claim in folder if claim not in aside]
        ticket = tickets.get(ticket_id)
        if ticket_id in set_aside:
            for claim in valid:
                fenced.setdefault(claim.hash, "its ticket is set aside")
            continue
        if ticket is None:
            set_aside[ticket_id] = "claims without a ticket"
            for claim in folder:
                put_aside(claim, "claims without a ticket", holds=False)
            continue
        opens = [claim for claim in valid if isinstance(claim, Claim)]
        if ticket.is_terminal:
            for claim in opens:
                put_aside(claim, "an open claim on a resolved ticket", holds=False)
            holding.pop(ticket_id, None)
        elif len(opens) > 1:
            for claim in opens:
                put_aside(claim, "more than one open claim", holds=True)

    for claim, why in aside.items():
        fenced.setdefault(claim.hash, why)
    claims: dict[TicketId, Claim] = {}
    ended: dict[ClaimHash, EndedClaim] = {}
    for claim in files:
        if claim in aside or claim.ticket_id in set_aside:
            continue
        if isinstance(claim, Claim):
            claims[claim.ticket_id] = claim
        else:
            ended[claim.hash] = claim
    for claim_hash in [*(claim.hash for claim in claims.values()), *ended]:
        fenced.pop(claim_hash, None)  # a valid file wins: the rules follow it
    held = {
        ticket_id: why
        for ticket_id, why in holding.items()
        if ticket_id in tickets and ticket_id not in claims and not tickets[ticket_id].is_terminal
    }
    return Snapshot(
        revision,
        MappingProxyType(dict(tickets)),
        claims=MappingProxyType(claims),
        ended=MappingProxyType(ended),
        set_aside=MappingProxyType(set_aside),
        held_aside=MappingProxyType(held),
        fenced=MappingProxyType(fenced),
    )


def after(snapshot: Snapshot, changes: Iterable[Change], revision: Revision) -> Snapshot:
    """The snapshot `changes` lead to from `snapshot`, at `revision`: what a store holds
    once they are committed. Built from the valid tickets and claims only, so it carries
    nothing set aside: a store that never sees forged files (MemStore) or a caller that
    only reports the tickets an op wrote can use it."""
    tickets = dict(snapshot.tickets)
    files: dict[ClaimFile, None] = dict.fromkeys(
        [*snapshot.claims.values(), *snapshot.ended.values()]
    )
    for change in changes:
        match change:
            case WriteTicket(ticket=ticket):
                tickets[ticket.id] = ticket
            case WriteClaim(claim=claim, replaces=replaced):
                if replaced is not None:
                    files.pop(replaced, None)
                files[claim] = None
    return assemble(revision, tickets, {}, files)
