"""Who holds what: the snapshot assembled from tickets and claim files (ADR 0007).

PURE module. A store hands over the valid tickets, the ticket ids it set aside, and
every claim file whose name parsed; `assemble` runs ADR 0007's checks in their fixed
order, so every reader reaches the same verdict:

1. each file: in a folder that is not one (a `claims/<id>` that can't be written, as it
   holds a name with '/') or times out of order (which tkt never writes) -> set aside;
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
    TicketState,
)

NOT_A_FOLDER = "its claims folder is not a folder"


def assemble(
    revision: Revision | None,
    tickets: Mapping[TicketId, Ticket],
    set_aside: Mapping[TicketId, str],
    claim_files: Iterable[ClaimFile],
    not_folders: Iterable[TicketId] = (),
) -> Snapshot:
    """The snapshot of `tickets` (all valid) and `claim_files` (every claim file whose
    name parsed), with `set_aside` the ticket ids whose files failed their checks and
    `not_folders` the ids whose `claims/<id>` is not a folder: its ticket is held by a
    set-aside claim (nothing in it can be read, so nothing can be known free), or, with
    no ticket, the id is set aside. Claim files in such a folder (one that can't be
    rewritten) are all set aside, so they still fence."""
    files = list(claim_files)  # a store lists each path once: no duplicates
    aside: dict[int, str] = {}  # index in `files` -> why; indices, as hashing claims is slow
    unwritable = set(not_folders)
    holding: dict[TicketId, str] = dict.fromkeys(unwritable, NOT_A_FOLDER)

    def put_aside(index: int, why: str, *, holds: bool) -> None:
        aside.setdefault(index, why)
        if holds and isinstance(claim := files[index], Claim):
            holding.setdefault(claim.ticket_id, why)

    for index, claim in enumerate(files):  # step 1
        end = claim.lease_until if isinstance(claim, Claim) else claim.ended_at
        if claim.ticket_id in unwritable:
            put_aside(index, NOT_A_FOLDER, holds=True)
        elif claim.claimed_at > end:
            put_aside(index, "a claim's times are out of order", holds=True)

    first: dict[ClaimHash, int] = {}
    repeated: dict[ClaimHash, list[int]] = {}
    for index, claim in enumerate(files):
        if index not in aside and (seen := first.setdefault(claim.hash, index)) != index:
            repeated.setdefault(claim.hash, [seen]).append(index)
    for same in repeated.values():  # step 2: only hashes found more than once
        if len({files[index].ticket_id for index in same}) > 1:
            for index in same:
                put_aside(index, "a claim hash is in more than one folder", holds=True)
        elif sum(isinstance(files[index], EndedClaim) for index in same) > 1:
            for index in same:
                put_aside(index, "a claim has ended more than once", holds=False)
        elif any(isinstance(files[index], EndedClaim) for index in same):
            for index in same:
                if isinstance(files[index], Claim):
                    put_aside(index, "a claim is both open and ended", holds=False)

    by_folder: dict[TicketId, list[int]] = defaultdict(list)
    for index, claim in enumerate(files):
        by_folder[claim.ticket_id].append(index)
    set_aside = dict(set_aside)
    for ticket_id in holding:
        if ticket_id not in tickets:
            set_aside.setdefault(ticket_id, NOT_A_FOLDER)
    fenced: dict[ClaimHash, str] = {}
    for ticket_id, folder in by_folder.items():  # step 3
        valid = [index for index in folder if index not in aside]
        ticket = tickets.get(ticket_id)
        if ticket_id in set_aside:
            for index in valid:
                fenced.setdefault(files[index].hash, "its ticket is set aside")
            continue
        if ticket is None:
            set_aside[ticket_id] = "claims without a ticket"
            for index in folder:
                put_aside(index, "claims without a ticket", holds=False)
            continue
        opens = [index for index in valid if isinstance(files[index], Claim)]
        if ticket.is_terminal:
            for index in opens:
                put_aside(index, "an open claim on a resolved ticket", holds=False)
            holding.pop(ticket_id, None)
        elif len(opens) > 1:
            for index in opens:
                put_aside(index, "more than one open claim", holds=True)

    for index, why in aside.items():
        fenced.setdefault(files[index].hash, why)
    claims: dict[TicketId, Claim] = {}
    ended: dict[ClaimHash, EndedClaim] = {}
    for index, claim in enumerate(files):
        if index in aside or claim.ticket_id in set_aside:
            continue
        if isinstance(claim, Claim):
            claims[claim.ticket_id] = claim
        else:
            ended[claim.hash] = claim
    if fenced:
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


def states_after(
    snapshot: Snapshot, changes: Iterable[Change], ticket_ids: Iterable[TicketId]
) -> tuple[TicketState, ...]:
    """The tickets `ticket_ids`, each with its open claim, once `changes` are applied to
    `snapshot`: what an op reports. Built from the changes alone, without assembling the
    whole store again."""
    tickets: dict[TicketId, Ticket] = {}
    claims: dict[TicketId, Claim | None] = {}
    for change in changes:
        match change:
            case WriteTicket(ticket=ticket):
                tickets[ticket.id] = ticket
            case WriteClaim(claim=Claim() as claim):
                claims[claim.ticket_id] = claim
            case WriteClaim(claim=EndedClaim() as claim):
                claims.setdefault(claim.ticket_id, None)
    states = []
    for ticket_id in ticket_ids:
        found = tickets.get(ticket_id) or snapshot.get(ticket_id)
        if found is not None:
            held = claims[ticket_id] if ticket_id in claims else snapshot.claim_of(ticket_id)
            states.append(TicketState(found, held))
    return tuple(states)


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
