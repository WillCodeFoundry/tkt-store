"""The snapshot assembled from tickets and claim files (domain/occupancy.py): ADR 0007's
verdicts, in their fixed order, so every reader reaches the same one."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tkt_store.domain.occupancy import NOT_A_FOLDER, after, assemble
from tkt_store.domain.outcomes import WriteClaim
from tkt_store.domain.ticket import (
    AgentId,
    Claim,
    ClaimFile,
    ClaimId,
    EndedBy,
    EndedClaim,
    Phase,
    Resolution,
    Revision,
    Snapshot,
    Ticket,
    TicketId,
    claim_hash,
)

NOW = 1_000_000
A = AgentId("coder-7")
T1 = TicketId("tkt-0001")
T2 = TicketId("tkt-0002")
H1 = claim_hash(ClaimId("1" * 32))
H2 = claim_hash(ClaimId("2" * 32))


def tkt(ticket_id: TicketId = T1, **fields: object) -> Ticket:
    base = Ticket(id=ticket_id, title="Expire tokens", created=0, updated=0, phase=Phase.QA)
    return replace(base, **fields)  # type: ignore[arg-type]


def opened(hashed: str = H1, on: TicketId = T1, claimed_at: int = NOW) -> Claim:
    return Claim(on, hashed, A, claimed_at, NOW + 600)  # type: ignore[arg-type]


def ended(hashed: str = H1, on: TicketId = T1, by: EndedBy = EndedBy.RELEASED) -> EndedClaim:
    return EndedClaim(on, hashed, A, NOW, by, NOW + 60)  # type: ignore[arg-type]


def snap(
    tickets: tuple[Ticket, ...],
    claims: tuple[Claim | EndedClaim, ...] = (),
    set_aside: dict[TicketId, str] | None = None,
) -> Snapshot:
    return assemble(Revision("r1"), {t.id: t for t in tickets}, set_aside or {}, claims)


def test_valid_claims_are_kept() -> None:
    s = snap((tkt(), tkt(T2)), (opened(), ended(H2, on=T2)))
    assert s.claim_of(T1) == opened() and s.ended == {H2: ended(H2, on=T2)}
    assert not (s.set_aside or s.held_aside or s.fenced)


def test_times_out_of_order_set_the_claim_aside_and_hold_the_ticket() -> None:
    s = snap((tkt(),), (opened(claimed_at=NOW + 10**6),))
    assert s.claim_of(T1) is None and H1 in s.fenced and T1 in s.held_aside


def test_one_hash_in_two_folders_sets_every_file_aside() -> None:
    s = snap((tkt(), tkt(T2)), (opened(), opened(on=T2)))
    assert not s.claims and H1 in s.fenced and set(s.held_aside) == {T1, T2}


def test_an_ended_file_wins_over_an_open_one_and_the_ticket_is_not_held() -> None:
    s = snap((tkt(),), (opened(), ended()))
    assert s.claim_of(T1) is None and s.ended == {H1: ended()}
    assert not s.held_aside and H1 not in s.fenced  # the valid ended file is what counts


def test_a_hash_that_ended_twice_is_set_aside_and_fenced() -> None:
    s = snap((tkt(),), (ended(), ended(by=EndedBy.DONE)))
    assert not s.ended and H1 in s.fenced and not s.held_aside


def test_claims_without_a_ticket_set_the_id_aside() -> None:
    s = snap((tkt(),), (opened(on=T2),))
    assert s.set_aside == {T2: "claims without a ticket"} and H1 in s.fenced


def test_claims_on_a_set_aside_ticket_fence_but_never_count() -> None:
    s = snap((tkt(),), (opened(on=T2),), set_aside={T2: "not JSON"})
    assert s.set_aside == {T2: "not JSON"} and H1 in s.fenced and not s.claims


def test_a_resolution_wins_over_an_open_claim() -> None:
    s = snap((tkt(resolution=Resolution.DONE),), (opened(), opened(H2)))
    assert not s.claims and not s.held_aside and {H1, H2} <= set(s.fenced)


def test_several_open_claims_on_one_ticket_hold_it() -> None:
    s = snap((tkt(),), (opened(), opened(H2)))
    assert not s.claims and T1 in s.held_aside and {H1, H2} <= set(s.fenced)


def test_a_valid_open_claim_beside_a_bad_one_stands() -> None:
    """Step 3 counts only the claims still valid after steps 1 and 2."""
    s = snap((tkt(),), (opened(), opened(H2, claimed_at=NOW + 10**6)))
    assert s.claim_of(T1) == opened() and T1 not in s.held_aside


@pytest.mark.parametrize("reverse", [False, True])
def test_the_verdict_does_not_depend_on_listing_order(reverse: bool) -> None:
    files = (opened(), opened(H2), ended(H2))
    s = snap((tkt(),), tuple(reversed(files)) if reverse else files)
    assert s.claim_of(T1) == opened() and H2 in s.ended and not s.held_aside


def test_after_renames_a_claim() -> None:
    before = snap((tkt(),), (opened(),))
    result = after(
        before, (WriteClaim(opened().ended(EndedBy.DONE, NOW), opened()),), Revision("r2")
    )
    assert result.claim_of(T1) is None and result.ended[H1].ended_by is EndedBy.DONE


def test_a_claims_folder_that_is_not_a_folder_holds_its_ticket() -> None:
    s = assemble(Revision("r1"), {T1: tkt()}, {}, [], not_folders=[T1, T2])
    assert s.held_aside == {T1: "its claims folder is not a folder"}
    assert s.set_aside == {T2: "its claims folder is not a folder"}  # no ticket: the id


def test_claims_in_a_folder_that_is_not_one_are_set_aside_and_fence() -> None:
    """A folder that can't be rewritten (it holds a name with '/'): its ticket is held,
    and every claim in it is set aside, so its hashes still fence."""
    files: list[ClaimFile] = [opened(H1), ended(H2, by=EndedBy.RELEASED)]
    snapshot = assemble(None, {T1: tkt()}, {}, files, not_folders=[T1])
    assert not snapshot.claims and not snapshot.ended
    assert snapshot.held_aside == {T1: NOT_A_FOLDER}
    assert snapshot.fenced == {H1: NOT_A_FOLDER, H2: NOT_A_FOLDER}
