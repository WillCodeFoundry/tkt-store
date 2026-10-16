"""Rules are pure: every transition and refusal, tested without git or real time.

The holder-op cases mirror the table in docs/design.md §5; claims are files of their
own (ADR 0007), built here as `Claim` and `EndedClaim` values.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tkt_store.domain import fields
from tkt_store.domain.occupancy import after, assemble
from tkt_store.domain.operations import (
    AddOp,
    CancelOp,
    ClaimNextOp,
    ClaimOp,
    DoneOp,
    EditOp,
    InitOp,
    MoveOp,
    Op,
    OpName,
    ReapOp,
    ReleaseOp,
    RenewOp,
)
from tkt_store.domain.outcomes import Apply, Decision, NoOp, Refusal, RefusalCode, WriteClaim
from tkt_store.domain.rules import decide
from tkt_store.domain.ticket import (
    MAX_TTL,
    SKEW_GRACE,
    AgentId,
    Claim,
    ClaimId,
    EndedBy,
    EndedClaim,
    Kind,
    Phase,
    ProjectId,
    Resolution,
    Revision,
    Snapshot,
    Ticket,
    TicketId,
    claim_hash,
)

NOW = 1_000_000
TTL = 1800
A = AgentId("coder-7")
B = AgentId("reviewer-2")
C1 = ClaimId("1" * 32)
C2 = ClaimId("2" * 32)
C3 = ClaimId("3" * 32)
T1 = TicketId("tkt-0001")
T2 = TicketId("tkt-0002")
T3 = TicketId("tkt-0003")
LAPSED = NOW - 1  # a lease_until in the past, still within the grace
TAKEABLE = NOW - SKEW_GRACE  # lease_until + SKEW_GRACE == NOW


def tkt(ticket_id: TicketId = T1, **fields_: object) -> Ticket:
    """An open ticket in the implementation phase; `fields_` override."""
    base = Ticket(
        id=ticket_id, created=0, title="Expire tokens", updated=0, phase=Phase.IMPLEMENTATION
    )
    return replace(base, **fields_)  # type: ignore[arg-type]


def held(
    claim_id: ClaimId = C1, agent: AgentId = A, lease_until: int = NOW + 600, on: TicketId = T1
) -> Claim:
    """An open claim on `on`, taken 10 minutes before NOW and, by default, live for 10 more."""
    return Claim(on, claim_hash(claim_id), agent, NOW - 600, lease_until)


def gone(claim_id: ClaimId = C1, on: TicketId = T1, by: EndedBy = EndedBy.RELEASED) -> EndedClaim:
    """A claim on `on` that ended `by`, five minutes before NOW."""
    return EndedClaim(on, claim_hash(claim_id), A, NOW - 600, by, NOW - 300)


def snap(*items: Ticket | Claim | EndedClaim) -> Snapshot:
    """A snapshot at an arbitrary revision holding these tickets and claim files."""
    tickets = {item.id: item for item in items if isinstance(item, Ticket)}
    claims = [item for item in items if not isinstance(item, Ticket)]
    return assemble(Revision("r1"), tickets, {}, claims)


def applied(snapshot: Snapshot, decision: Decision) -> Snapshot:
    """The snapshot `decision` (an Apply) leads to."""
    assert isinstance(decision, Apply), decision
    return after(snapshot, decision.changes, Revision("r2"))


def refused(decision: Decision, code: RefusalCode) -> Refusal:
    assert isinstance(decision, Refusal), decision
    assert decision.code is code, decision
    return decision


def noop(decision: Decision) -> NoOp:
    assert isinstance(decision, NoOp), decision
    return decision


class TestClaim:
    def test_claims_open_ticket(self) -> None:
        s = snap(tkt())
        decision = decide(s, ClaimOp(T1, A, C1, TTL), NOW)
        assert applied(s, decision).claim_of(T1) == Claim(T1, claim_hash(C1), A, NOW, NOW + TTL)
        assert isinstance(decision, Apply) and decision.record.op is OpName.CLAIM

    def test_a_claim_never_writes_the_ticket(self) -> None:
        decision = decide(snap(tkt()), ClaimOp(T1, A, C1, TTL), NOW)
        assert isinstance(decision, Apply)
        assert all(isinstance(change, WriteClaim) for change in decision.changes)

    def test_refuses_live_claim_by_other(self) -> None:
        decision = decide(snap(tkt(), held(C2, B)), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)

    def test_same_claim_id_and_agent_is_noop(self) -> None:
        decision = decide(snap(tkt(), held()), ClaimOp(T1, A, C1, TTL), NOW)
        assert noop(decision).ticket_ids == (T1,)

    def test_same_claim_id_and_agent_renews_a_lapsed_claim(self) -> None:
        lapsed = held(lease_until=TAKEABLE)
        s = snap(tkt(), lapsed)
        claim = applied(s, decide(s, ClaimOp(T1, A, C1, TTL), NOW)).claim_of(T1)
        assert claim == replace(lapsed, lease_until=NOW + TTL)

    def test_same_claim_id_other_agent_is_already_claimed(self) -> None:
        decision = decide(snap(tkt(), held()), ClaimOp(T1, B, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)

    def test_takes_over_expired_claim(self) -> None:
        s = snap(tkt(), held(C2, B, TAKEABLE))
        result = applied(s, decide(s, ClaimOp(T1, A, C1, TTL), NOW))
        claim = result.claim_of(T1)
        assert claim is not None and claim.hash == claim_hash(C1)
        assert result.ended[claim_hash(C2)].ended_by is EndedBy.TAKEN_OVER

    def test_refuses_blocked(self) -> None:
        decision = decide(snap(tkt(blocked_by=(T2,)), tkt(T2)), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.BLOCKED)

    def test_refuses_blocked_even_with_a_lapsed_claim(self) -> None:
        s = snap(tkt(blocked_by=(T2,)), held(C2, B, TAKEABLE), tkt(T2))
        refused(decide(s, ClaimOp(T1, A, C1, TTL), NOW), RefusalCode.BLOCKED)

    @pytest.mark.parametrize("resolution", list(Resolution))
    def test_refuses_terminal(self, resolution: Resolution) -> None:
        decision = decide(snap(tkt(resolution=resolution)), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.TERMINAL)

    @pytest.mark.parametrize("where", ["this_ticket", "another_ticket"])
    @pytest.mark.parametrize("ending", list(EndedBy))
    def test_ended_claim_id_cannot_claim_again(self, ending: EndedBy, where: str) -> None:
        resolution = {EndedBy.CANCELLED: Resolution.CANCELLED, EndedBy.DONE: Resolution.DONE}
        ended = tkt(T2, resolution=resolution.get(ending))
        target = T2 if where == "this_ticket" and ended.resolution is None else T1
        s = snap(tkt(), ended, gone(C1, T2, ending))
        refused(decide(s, ClaimOp(target, A, C1, TTL), NOW), RefusalCode.NOT_HOLDER)

    def test_claim_id_live_on_another_ticket_is_already_claimed(self) -> None:
        s = snap(tkt(), tkt(T2), held(on=T2))
        refused(decide(s, ClaimOp(T1, A, C1, TTL), NOW), RefusalCode.ALREADY_CLAIMED)


class TestSkewGrace:
    def test_no_takeover_within_grace(self) -> None:
        decision = decide(snap(tkt(), held(C2, B, LAPSED)), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)

    def test_takeover_allowed_after_grace(self) -> None:
        decision = decide(snap(tkt(), held(C2, B, TAKEABLE)), ClaimOp(T1, A, C1, TTL), NOW)
        assert isinstance(decision, Apply)

    def test_no_reap_within_grace(self) -> None:
        noop(decide(snap(tkt(), held(lease_until=LAPSED)), ReapOp(), NOW))

    def test_holder_may_renew_within_grace(self) -> None:
        s = snap(tkt(), held(lease_until=LAPSED))
        claim = applied(s, decide(s, RenewOp(T1, C1, TTL), NOW)).claim_of(T1)
        assert claim is not None and claim.lease_until == NOW + TTL


class TestClocks:
    """tkt never writes a claim file it would set aside (ADR 0007)."""

    def test_an_end_is_never_before_the_claim(self) -> None:
        future = Claim(T1, claim_hash(C1), A, NOW + 30, NOW + 600)  # the claimer's clock is ahead
        s = snap(tkt(), future)
        ended = applied(s, decide(s, CancelOp(T1), NOW)).ended[claim_hash(C1)]
        assert ended.ended_at == NOW + 30

    def test_a_renewal_is_never_before_the_claim(self) -> None:
        future = Claim(T1, claim_hash(C1), A, NOW + TTL + 30, NOW + TTL + 600)
        s = snap(tkt(), future)
        claim = applied(s, decide(s, RenewOp(T1, C1, TTL), NOW)).claim_of(T1)
        assert claim is not None and claim.lease_until == NOW + TTL + 30


HOLDER_STATES: dict[str, tuple[Ticket | Claim | EndedClaim, ...]] = {
    "resolved": (tkt(resolution=Resolution.DONE), gone(C2, by=EndedBy.DONE)),
    "cancelled": (tkt(resolution=Resolution.CANCELLED),),
    "done_same_claim": (tkt(resolution=Resolution.DONE), gone(C2), gone(C1, by=EndedBy.DONE)),
    "done_other_claim": (tkt(resolution=Resolution.DONE), gone(C1), gone(C2, by=EndedBy.DONE)),
    "current_match": (tkt(), held()),
    "current_match_already_in_phase": (tkt(phase=Phase.REVIEW), held()),
    "ended_match": (tkt(), gone()),
    "ended_match_already_in_phase": (tkt(phase=Phase.REVIEW), gone()),
    "ended_match_other_phase": (tkt(), gone()),
    "no_claim": (tkt(),),
    "other_claim": (tkt(), held(C2, B)),
}

HOLDER_OPS: dict[str, RenewOp | MoveOp | ReleaseOp | DoneOp] = {
    "renew": RenewOp(T1, C1, TTL),
    "move": MoveOp(T1, C1, Phase.REVIEW),
    "release": ReleaseOp(T1, C1),
    "done": DoneOp(T1, C1),
}


class TestHolderOps:
    """docs/design.md §5, holder-op table, checked in the documented order."""

    @pytest.mark.parametrize(
        ("op", "state", "expected"),
        [
            ("renew", "resolved", "TERMINAL"),
            ("move", "resolved", "TERMINAL"),
            ("release", "resolved", "TERMINAL"),
            ("done", "cancelled", "TERMINAL"),
            ("done", "done_same_claim", "NoOp"),
            ("done", "done_other_claim", "NOT_HOLDER"),
            ("renew", "current_match", "Apply"),
            ("move", "current_match", "Apply"),
            ("move", "current_match_already_in_phase", "NoOp"),
            ("release", "current_match", "Apply"),
            ("done", "current_match", "Apply"),
            ("renew", "ended_match", "NOT_HOLDER"),
            ("move", "ended_match_already_in_phase", "NoOp"),
            ("move", "ended_match_other_phase", "NOT_HOLDER"),
            ("release", "ended_match", "NoOp"),
            ("done", "ended_match", "NOT_HOLDER"),
            ("renew", "no_claim", "NOT_CLAIMED"),
            ("move", "no_claim", "NOT_CLAIMED"),
            ("release", "no_claim", "NOT_CLAIMED"),
            ("done", "no_claim", "NOT_CLAIMED"),
            ("renew", "other_claim", "NOT_HOLDER"),
            ("move", "other_claim", "NOT_HOLDER"),
            ("release", "other_claim", "NOT_HOLDER"),
            ("done", "other_claim", "NOT_HOLDER"),
        ],
    )
    def test_table(self, op: str, state: str, expected: str) -> None:
        decision = decide(snap(*HOLDER_STATES[state]), HOLDER_OPS[op], NOW)
        if expected == "Apply":
            assert isinstance(decision, Apply), decision
        elif expected == "NoOp":
            noop(decision)
        else:
            refused(decision, RefusalCode(expected))

    def test_ended_match_wins_over_claimed_by_another(self) -> None:
        noop(decide(snap(tkt(), gone(), held(C2, B)), ReleaseOp(T1, C1), NOW))

    def test_release_rerun_after_push_landed_is_noop(self) -> None:
        s = snap(tkt(), held())
        released = applied(s, decide(s, ReleaseOp(T1, C1), NOW))
        noop(decide(released, ReleaseOp(T1, C1), NOW))

    def test_reaped_holder_plain_release_is_noop_with_claim_ended_reason(self) -> None:
        decision = decide(snap(tkt(), gone(by=EndedBy.REAPED)), ReleaseOp(T1, C1), NOW)
        assert "already ended" in noop(decision).reason

    def test_reaped_holder_cannot_move_the_phase(self) -> None:
        decision = decide(snap(tkt(), gone(by=EndedBy.REAPED)), MoveOp(T1, C1, Phase.REVIEW), NOW)
        refused(decision, RefusalCode.NOT_HOLDER)

    def test_rerun_converges_after_several_claim_cycles(self) -> None:
        noop(decide(snap(tkt(), gone(C1), gone(C2), gone(C3)), ReleaseOp(T1, C1), NOW))

    @pytest.mark.parametrize(
        ("state", "text"),
        [
            ((tkt(), gone()), "already ended"),
            ((tkt(),), "never used"),
            ((tkt(), held(C2, B)), "held by another claim"),
        ],
        ids=["already_ended", "never_used", "held_by_another"],
    )
    def test_refusal_message_says_which_case(
        self, state: tuple[Ticket | Claim | EndedClaim, ...], text: str
    ) -> None:
        decision = decide(snap(*state), RenewOp(T1, C1, TTL), NOW)
        assert isinstance(decision, Refusal) and text in decision.message

    def test_refusals_never_echo_a_claim_id_or_hash(self) -> None:
        decision = decide(snap(tkt(), held(C2, B)), RenewOp(T1, C1, TTL), NOW)
        assert isinstance(decision, Refusal)
        assert C1 not in decision.message and claim_hash(C1) not in decision.message

    def test_done_by_stale_holder_after_takeover(self) -> None:
        s = snap(tkt(), held(C2, B), gone(by=EndedBy.TAKEN_OVER))
        refused(decide(s, DoneOp(T1, C1), NOW), RefusalCode.NOT_HOLDER)

    def test_done_records_resolution_and_ends_the_claim(self) -> None:
        s = snap(tkt(), held())
        result = applied(s, decide(s, DoneOp(T1, C1), NOW))
        ticket = result.get(T1)
        assert ticket is not None and ticket.resolution is Resolution.DONE
        assert ticket.phase is Phase.IMPLEMENTATION and result.claim_of(T1) is None
        assert result.ended[claim_hash(C1)].ended_by is EndedBy.DONE

    def test_done_rerun_needs_the_ticket_done_and_the_claim_ended_by_done(self) -> None:
        released_on_done = snap(tkt(resolution=Resolution.DONE), gone(C1))
        refused(decide(released_on_done, DoneOp(T1, C1), NOW), RefusalCode.NOT_HOLDER)

    def test_done_on_lapsed_claim_not_taken_over(self) -> None:
        decision = decide(snap(tkt(), held(lease_until=TAKEABLE)), DoneOp(T1, C1), NOW)
        assert isinstance(decision, Apply)

    def test_done_is_not_gated_by_blockers(self) -> None:
        decision = decide(snap(tkt(blocked_by=(T2,)), held(), tkt(T2)), DoneOp(T1, C1), NOW)
        assert isinstance(decision, Apply)

    @pytest.mark.parametrize(
        ("ending", "by"),
        [
            (ReleaseOp(T1, C1), EndedBy.RELEASED),
            (ReapOp(), EndedBy.REAPED),
            (ClaimOp(T1, B, C2, TTL), EndedBy.TAKEN_OVER),
            (CancelOp(T1), EndedBy.CANCELLED),
            (DoneOp(T1, C1), EndedBy.DONE),
        ],
        ids=["release", "reap", "takeover", "cancel", "done"],
    )
    def test_ending_a_claim_records_how(self, ending: Op, by: EndedBy) -> None:
        s = snap(tkt(), held(lease_until=TAKEABLE), gone(C3))
        result = applied(s, decide(s, ending, NOW))
        assert result.ended[claim_hash(C1)].ended_by is by
        assert claim_hash(C3) in result.ended

    def test_stale_release_after_completion_is_terminal(self) -> None:
        decision = decide(snap(*HOLDER_STATES["resolved"]), ReleaseOp(T1, C1), NOW)
        refused(decision, RefusalCode.TERMINAL)


class TestIdempotence:
    def test_add_same_id_same_content_is_noop(self) -> None:
        existing = tkt(created=5, updated=7)
        noop(decide(snap(existing), AddOp(T1, "Expire tokens", phase=Phase.TRIAGE), NOW))

    @pytest.mark.parametrize("since", ["move", "claim", "release", "done"])
    def test_add_rerun_after_workflow_or_occupancy_change_is_noop(self, since: str) -> None:
        changed = {
            "move": (tkt(phase=Phase.REVIEW),),
            "claim": (tkt(), held()),
            "release": (tkt(), gone()),
            "done": (tkt(resolution=Resolution.DONE), gone(by=EndedBy.DONE)),
        }[since]
        noop(decide(snap(*changed), AddOp(T1, "Expire tokens", phase=Phase.TRIAGE), NOW))

    def test_add_rerun_after_edit_is_noop(self) -> None:
        edited = tkt(title="Renamed", content_version=2)
        noop(decide(snap(edited), AddOp(T1, "Expire tokens"), NOW))

    @pytest.mark.parametrize("field", ["kind", "project"])
    def test_add_with_different_identity_is_duplicate_id(self, field: str) -> None:
        op = (
            AddOp(T1, "Expire tokens", kind=Kind.BUG)
            if field == "kind"
            else AddOp(T1, "Expire tokens", project=ProjectId("other"))
        )
        refused(decide(snap(tkt()), op, NOW), RefusalCode.DUPLICATE_ID)

    def test_add_same_id_different_content_is_refused(self) -> None:
        refused(decide(snap(tkt()), AddOp(T1, "Something else"), NOW), RefusalCode.DUPLICATE_ID)

    def test_done_twice_is_noop(self) -> None:
        s = snap(tkt(), held())
        done = applied(s, decide(s, DoneOp(T1, C1), NOW))
        noop(decide(done, DoneOp(T1, C1), NOW))


class TestWorkflow:
    def test_move_changes_phase_and_keeps_the_claim(self) -> None:
        s = snap(tkt(), held())
        decision = decide(s, MoveOp(T1, C1, Phase.REVIEW), NOW)
        result = applied(s, decision)
        ticket = result.get(T1)
        assert ticket is not None and ticket.phase is Phase.REVIEW
        assert result.claim_of(T1) == held()
        assert isinstance(decision, Apply) and decision.record.phase is Phase.REVIEW

    def test_handoff_is_move_then_release(self) -> None:
        s = snap(tkt(), held())
        moved = applied(s, decide(s, MoveOp(T1, C1, Phase.REVIEW), NOW))
        released = applied(moved, decide(moved, ReleaseOp(T1, C1), NOW))
        ticket = released.get(T1)
        assert ticket is not None and ticket.phase is Phase.REVIEW
        assert released.claim_of(T1) is None

    def test_add_starts_unresolved_in_its_phase(self) -> None:
        s = snap()
        ticket = applied(s, decide(s, AddOp(T1, "New", phase=Phase.QA), NOW)).get(T1)
        assert ticket is not None
        assert (ticket.resolution, ticket.phase, ticket.content_version) == (None, Phase.QA, 1)
        assert ticket.created == ticket.updated == NOW

    def test_cancel_keeps_the_phase_and_ends_the_claim(self) -> None:
        s = snap(tkt(phase=Phase.REVIEW), held())
        result = applied(s, decide(s, CancelOp(T1), NOW))
        ticket = result.get(T1)
        assert ticket is not None and ticket.resolution is Resolution.CANCELLED
        assert ticket.phase is Phase.REVIEW and result.claim_of(T1) is None
        assert result.ended[claim_hash(C1)].ended_by is EndedBy.CANCELLED

    def test_cancel_done_ticket_is_terminal(self) -> None:
        decision = decide(snap(tkt(resolution=Resolution.DONE)), CancelOp(T1), NOW)
        refused(decision, RefusalCode.TERMINAL)

    def test_cancel_twice_is_noop(self) -> None:
        noop(decide(snap(tkt(resolution=Resolution.CANCELLED)), CancelOp(T1), NOW))

    def test_cancelled_blocker_does_not_satisfy_dependency(self) -> None:
        tickets = snap(tkt(blocked_by=(T2,)), tkt(T2, resolution=Resolution.CANCELLED))
        refused(decide(tickets, ClaimOp(T1, A, C1, TTL), NOW), RefusalCode.BLOCKED)


class TestValidation:
    @pytest.mark.parametrize(
        "ticket_id", ["tkt-XYZ", "tkt-../x", "x/tkt-0001", "tkt-", "TKT-1", "tkt-0001\n"]
    )
    def test_bad_ticket_id_is_invalid(self, ticket_id: str) -> None:
        bad = TicketId(ticket_id)
        refused(decide(snap(tkt()), AddOp(bad, "T"), NOW), RefusalCode.INVALID)
        refused(decide(snap(tkt()), AddOp(T2, "T", blocked_by=(bad,)), NOW), RefusalCode.INVALID)

    @pytest.mark.parametrize(
        "claim_id", ["0", "abc", "A" * 32, "0" * 31, "0" * 33, "0" * 32 + "\n"]
    )
    def test_bad_claim_id_is_invalid(self, claim_id: str) -> None:
        decision = decide(snap(tkt()), ClaimOp(T1, A, ClaimId(claim_id), TTL), NOW)
        refused(decision, RefusalCode.INVALID)

    @pytest.mark.parametrize("field", ["agent", "reason", "title"])
    def test_control_characters_are_invalid(self, field: str) -> None:
        options: dict[str, Op] = {
            "agent": ClaimOp(T1, AgentId("a\nb"), C1, TTL),
            "reason": CancelOp(T1, reason="x\ntkt-op: done"),
            "title": AddOp(T2, "line\nbreak"),
        }
        op = options[field]
        refused(decide(snap(tkt()), op, NOW), RefusalCode.INVALID)

    @pytest.mark.parametrize("ttl", [0, -1, MAX_TTL + 1])
    @pytest.mark.parametrize("op", ["claim", "claim-next", "renew"])
    def test_ttl_out_of_bounds_is_invalid(self, op: str, ttl: int) -> None:
        options: dict[str, Op] = {
            "claim": ClaimOp(T1, A, C1, ttl),
            "claim-next": ClaimNextOp(A, C1, ttl),
            "renew": RenewOp(T1, C1, ttl),
        }
        operation = options[op]
        refused(decide(snap(tkt(), held()), operation, NOW), RefusalCode.INVALID)

    @pytest.mark.parametrize(
        "op",
        [
            EditOp(T1, 1, title="  "),
            EditOp(T1, 1, blocked_by=(T1,)),
            EditOp(T1, 1, blocked_by=(T3,)),
            EditOp(T1, 1, blocked_by=(T2,)),
        ],
        ids=["empty_title", "self_blocker", "unknown_blocker", "cycle"],
    )
    def test_edit_validates_like_add(self, op: EditOp) -> None:
        tickets = snap(tkt(), tkt(T2, blocked_by=(T1,)))  # T2 already depends on T1
        refused(decide(tickets, op, NOW), RefusalCode.INVALID)

    @pytest.mark.parametrize("expected_version", [0, -1])
    def test_bad_expected_version_is_invalid(self, expected_version: int) -> None:
        decision = decide(snap(tkt()), EditOp(T1, expected_version, title="X"), NOW)
        refused(decision, RefusalCode.INVALID)

    def test_a_stored_value_that_breaks_a_rule_blocks_every_write_of_the_ticket(self) -> None:
        """tkt never writes an invalid ticket, whichever field the op changes."""
        ticket = tkt(title="written before the rules ")
        refused(decide(snap(ticket), EditOp(T1, 1, priority=5), NOW), RefusalCode.INVALID)
        refused(decide(snap(ticket), CancelOp(T1), NOW), RefusalCode.INVALID)

    def test_a_ticket_file_over_the_cap_is_invalid(self) -> None:
        big = "\U0001f600" * fields.BODY_MAX  # 4 bytes each in UTF-8: the file passes 256 KiB
        refused(decide(snap(tkt()), EditOp(T1, 1, body=big), NOW), RefusalCode.INVALID)

    def test_validation_wins_over_every_other_outcome(self) -> None:
        refused(decide(snap(), RenewOp(T1, ClaimId("bad"), TTL), NOW), RefusalCode.INVALID)


def aside(
    *items: Ticket | Claim | EndedClaim,
    set_aside: dict[TicketId, str] | None = None,
) -> Snapshot:
    """`snap`, plus ticket ids set aside on reading."""
    tickets = {item.id: item for item in items if isinstance(item, Ticket)}
    claims = [item for item in items if not isinstance(item, Ticket)]
    return assemble(Revision("r1"), tickets, set_aside or {}, claims)


class TestSetAside:
    """SET_ASIDE in ADR 0007's order: after INVALID, before every rule's refusals."""

    @pytest.mark.parametrize(
        "op",
        [
            AddOp(T2, "Expire tokens"),
            EditOp(T2, 1, title="X"),
            ClaimOp(T2, A, C1, TTL),
            RenewOp(T2, C1, TTL),
            CancelOp(T2),
            AddOp(T3, "Blocked", blocked_by=(T2,)),
            EditOp(T1, 1, blocked_by=(T2,)),
        ],
        ids=["add", "edit", "claim", "renew", "cancel", "add_blocked_by", "edit_blocked_by"],
    )
    def test_an_op_naming_a_set_aside_ticket(self, op: Op) -> None:
        s = aside(tkt(), set_aside={T2: "not JSON"})
        refusal = refused(decide(s, op, NOW), RefusalCode.SET_ASIDE)
        assert "not JSON" in refusal.message

    def test_an_edit_whose_existing_blocker_is_set_aside(self) -> None:
        s = aside(tkt(blocked_by=(T2,)), set_aside={T2: "not JSON"})
        refused(decide(s, EditOp(T1, 1, title="X"), NOW), RefusalCode.SET_ASIDE)

    def test_a_set_aside_blocker_is_only_not_done_for_a_claim(self) -> None:
        s = aside(tkt(blocked_by=(T2,)), set_aside={T2: "not JSON"})
        refused(decide(s, ClaimOp(T1, A, C1, TTL), NOW), RefusalCode.BLOCKED)

    def test_add_of_an_id_with_claims_but_no_ticket(self) -> None:
        s = snap(tkt(), held(C2, on=T2))
        refused(decide(s, AddOp(T2, "Expire tokens"), NOW), RefusalCode.SET_ASIDE)

    def test_invalid_wins_over_set_aside(self) -> None:
        s = aside(tkt(), set_aside={T2: "not JSON"})
        refused(decide(s, ClaimOp(T2, A, ClaimId("bad"), TTL), NOW), RefusalCode.INVALID)

    @pytest.mark.parametrize(
        "op",
        [
            ClaimOp(T1, B, C3, TTL),
            RenewOp(T1, C1, TTL),
            ReleaseOp(T1, C1),
            EditOp(T1, 1, title="X"),
        ],
        ids=["fresh_claim", "renew", "release", "edit"],
    )
    def test_a_ticket_held_by_a_set_aside_claim(self, op: Op) -> None:
        """Two open claims on one ticket: both are set aside and the ticket is held."""
        s = snap(tkt(), held(C1), held(C2, B))
        refused(decide(s, op, NOW), RefusalCode.SET_ASIDE)

    def test_cancel_always_resolves_a_ticket_held_by_a_set_aside_claim(self) -> None:
        s = snap(tkt(), held(C1), held(C2, B))
        assert isinstance(decide(s, CancelOp(T1), NOW), Apply)

    def test_claim_next_passes_over_a_ticket_held_by_a_set_aside_claim(self) -> None:
        s = snap(tkt(priority=0), held(C1), held(C2, B), tkt(T2, priority=50))
        result = applied(s, decide(s, ClaimNextOp(A, C3, TTL), NOW))
        claim = result.claim_of(T2)
        assert claim is not None and claim.hash == claim_hash(C3)

    def test_reap_leaves_set_aside_claims_alone(self) -> None:
        s = snap(tkt(), held(C1, A, TAKEABLE), held(C2, B, TAKEABLE))
        noop(decide(s, ReapOp(), NOW))

    def test_a_re_run_whose_claim_is_set_aside_never_takes_a_second_ticket(self) -> None:
        """C1 is in two folders: set aside, still fenced; claim-next with it is refused."""
        s = snap(tkt(), held(C1), tkt(T2), held(C1, on=T2), tkt(T3))
        refused(decide(s, ClaimNextOp(A, C1, TTL), NOW), RefusalCode.SET_ASIDE)

    def test_a_claim_on_a_set_aside_ticket_fences_its_hash(self) -> None:
        s = aside(tkt(), held(C1, on=T2), set_aside={T2: "not JSON"})
        refused(decide(s, ClaimNextOp(A, C1, TTL), NOW), RefusalCode.SET_ASIDE)

    def test_an_ended_file_wins_over_an_open_one_with_its_hash(self) -> None:
        """The claim provably ended: the ticket is not held, the rules follow the end."""
        s = snap(tkt(), held(C1), gone(C1))
        assert s.claim_of(T1) is None and T1 not in s.held_aside
        noop(decide(s, ReleaseOp(T1, C1), NOW))

    def test_a_resolution_wins_over_an_open_claim(self) -> None:
        s = snap(tkt(resolution=Resolution.DONE), held(C1), gone(C2, by=EndedBy.DONE))
        assert s.claim_of(T1) is None and T1 not in s.held_aside
        noop(decide(s, DoneOp(T1, C2), NOW))


class TestClaimNext:
    def test_picks_highest_priority_then_oldest(self) -> None:
        s = snap(
            tkt(T1, priority=None, created=1),
            tkt(T2, priority=2, created=9),
            tkt(T3, priority=2, created=3),
        )
        assert applied(s, decide(s, ClaimNextOp(A, C1, TTL), NOW)).claim_of(T3) is not None

    def test_skips_blocked_and_terminal(self) -> None:
        s = snap(
            tkt(T1, priority=1, blocked_by=(T2,)),
            tkt(T2, priority=2, resolution=Resolution.CANCELLED),
            tkt(T3, priority=3),
        )
        assert applied(s, decide(s, ClaimNextOp(A, C1, TTL), NOW)).claim_of(T3) is not None

    def test_skips_claims_within_grace(self) -> None:
        s = snap(tkt(T1, priority=1), held(C2, B, LAPSED), tkt(T2, priority=2))
        assert applied(s, decide(s, ClaimNextOp(A, C1, TTL), NOW)).claim_of(T2) is not None

    def test_filters_by_project_kind_and_phase(self) -> None:
        s = snap(
            tkt(T1, project=ProjectId("p1"), kind=Kind.BUG, phase=Phase.REVIEW),
            tkt(T2, project=None, kind=Kind.BUG, phase=Phase.REVIEW),
        )
        op = ClaimNextOp(A, C1, TTL, project=ProjectId("p1"), kind=Kind.BUG, phase=Phase.REVIEW)
        assert applied(s, decide(s, op, NOW)).claim_of(T1) is not None

    def test_project_filter_matches_exact_value_only(self) -> None:
        decision = decide(
            snap(tkt(project=None)), ClaimNextOp(A, C1, TTL, project=ProjectId("p1")), NOW
        )
        refused(decision, RefusalCode.NOTHING_CLAIMABLE)

    def test_live_retry_is_noop_naming_the_ticket(self) -> None:
        s = snap(tkt(T1), tkt(T2), held(on=T2))
        assert noop(decide(s, ClaimNextOp(A, C1, TTL), NOW)).ticket_ids == (T2,)

    def test_lapsed_retry_never_takes_a_second_ticket(self) -> None:
        s = snap(tkt(T1, priority=1), tkt(T2), held(lease_until=TAKEABLE, on=T2))
        claim = applied(s, decide(s, ClaimNextOp(A, C1, TTL), NOW)).claim_of(T2)
        assert claim is not None and claim.lease_until == NOW + TTL

    def test_same_claim_id_other_agent_is_already_claimed(self) -> None:
        decision = decide(snap(tkt(), held()), ClaimNextOp(B, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)

    def test_ended_claim_id_is_refused(self) -> None:
        s = snap(tkt(), tkt(T2), gone(on=T2))
        refused(decide(s, ClaimNextOp(A, C1, TTL), NOW), RefusalCode.NOT_HOLDER)

    def test_nothing_claimable(self) -> None:
        decision = decide(snap(tkt(resolution=Resolution.DONE)), ClaimNextOp(A, C1, TTL), NOW)
        refused(decision, RefusalCode.NOTHING_CLAIMABLE)


class TestReap:
    def test_releases_all_expired_in_one_record(self) -> None:
        s = snap(
            tkt(T1),
            held(C1, A, TAKEABLE),
            tkt(T2, blocked_by=(T3,)),
            held(C2, B, TAKEABLE, on=T2),
            tkt(T3),
            held(C3, A, on=T3),
        )
        decision = decide(s, ReapOp(), NOW)
        assert isinstance(decision, Apply) and decision.record.ticket_ids == (T1, T2)
        result = applied(s, decision)
        assert result.ended[claim_hash(C1)].ended_by is EndedBy.REAPED
        assert result.claim_of(T2) is None and result.claim_of(T3) is not None

    def test_nothing_expired_is_noop(self) -> None:
        noop(decide(snap(tkt(), held()), ReapOp(), NOW))


class TestEdit:
    @pytest.mark.parametrize("state", ["missing", "resolved"])
    def test_refused_on_missing_or_terminal(self, state: str) -> None:
        tickets = snap() if state == "missing" else snap(tkt(resolution=Resolution.DONE))
        code = RefusalCode.NOT_FOUND if state == "missing" else RefusalCode.TERMINAL
        refused(decide(tickets, EditOp(T1, 1, title="X"), NOW), code)

    def test_adding_blocker_to_claimed_ticket_keeps_the_claim(self) -> None:
        s = snap(tkt(), held(), tkt(T2))
        result = applied(s, decide(s, EditOp(T1, 1, blocked_by=(T2,)), NOW))
        ticket = result.get(T1)
        assert result.claim_of(T1) == held() and ticket is not None and ticket.blocked_by == (T2,)

    def test_unset_fields_are_unchanged(self) -> None:
        s = snap(tkt(body="b", tags=("x",)))
        ticket = applied(s, decide(s, EditOp(T1, 1, title="New"), NOW)).get(T1)
        assert ticket is not None and (ticket.title, ticket.body, ticket.tags) == (
            "New",
            "b",
            ("x",),
        )

    def test_priority_none_clears_it(self) -> None:
        s = snap(tkt(priority=3))
        ticket = applied(s, decide(s, EditOp(T1, 1, priority=None), NOW)).get(T1)
        assert ticket is not None and ticket.priority is None

    def test_apply_increments_version(self) -> None:
        s = snap(tkt(content_version=4))
        ticket = applied(s, decide(s, EditOp(T1, 4, title="X"), NOW)).get(T1)
        assert ticket is not None and ticket.content_version == 5 and ticket.updated == NOW

    def test_stale_version_is_refused(self) -> None:
        decision = decide(snap(tkt(content_version=4)), EditOp(T1, 3, title="X"), NOW)
        refused(decision, RefusalCode.STALE)

    def test_rerun_of_landed_edit_is_noop(self) -> None:
        noop(decide(snap(tkt(title="X", content_version=5)), EditOp(T1, 4, title="X"), NOW))

    def test_two_editors_same_field_second_is_stale(self) -> None:
        s = snap(tkt(content_version=3))
        first = applied(s, decide(s, EditOp(T1, 3, title="A"), NOW))
        refused(decide(first, EditOp(T1, 3, title="B"), NOW), RefusalCode.STALE)

    @pytest.mark.parametrize(
        "op", ["claim", "claim-next", "renew", "move", "release", "done", "cancel", "reap"]
    )
    def test_only_edit_changes_the_version(self, op: str) -> None:
        s = snap(tkt(content_version=3), held(lease_until=TAKEABLE))
        options: dict[str, Op] = {
            "claim": ClaimOp(T1, A, C1, TTL),
            "claim-next": ClaimNextOp(A, C1, TTL),
            "renew": RenewOp(T1, C1, TTL),
            "move": MoveOp(T1, C1, Phase.REVIEW),
            "release": ReleaseOp(T1, C1),
            "done": DoneOp(T1, C1),
            "cancel": CancelOp(T1),
            "reap": ReapOp(),
        }
        ticket = applied(s, decide(s, options[op], NOW)).get(T1)
        assert ticket is not None and ticket.content_version == 3


class TestInitAndAdd:
    def test_add_on_unborn_store_is_not_initialised(self) -> None:
        unborn = Snapshot(None, {})
        refused(decide(unborn, AddOp(T1, "T"), NOW), RefusalCode.NOT_INITIALISED)

    def test_init_on_existing_store_is_noop(self) -> None:
        noop(decide(snap(), InitOp(), NOW))
        assert isinstance(decide(Snapshot(None, {}), InitOp(), NOW), Apply)

    @pytest.mark.parametrize("op", [MoveOp(T1, C1, Phase.QA), CancelOp(T1)])
    def test_every_ticket_write_sets_updated(self, op: MoveOp | CancelOp) -> None:
        s = snap(tkt(), held())
        ticket = applied(s, decide(s, op, NOW)).get(T1)
        assert ticket is not None and ticket.updated == NOW

    @pytest.mark.parametrize("op", [RenewOp(T1, C1, TTL), ReleaseOp(T1, C1)])
    def test_claim_ops_leave_the_ticket_alone(self, op: RenewOp | ReleaseOp) -> None:
        s = snap(tkt(), held())
        assert applied(s, decide(s, op, NOW)).get(T1) == tkt()


class TestRecord:
    def test_record_carries_injected_time_and_the_claim_hash(self) -> None:
        decision = decide(snap(tkt(), held()), RenewOp(T1, C1, TTL), NOW)
        assert isinstance(decision, Apply) and decision.record.at == NOW
        assert decision.record.claim_hash == claim_hash(C1)

    @pytest.mark.parametrize("op", ["add", "edit", "cancel"])
    def test_record_carries_optional_actor(self, op: str) -> None:
        options: dict[str, Op] = {
            "add": AddOp(T2, "T", agent=A),
            "edit": EditOp(T1, 1, title="X", agent=A),
            "cancel": CancelOp(T1, agent=A),
        }
        operation = options[op]
        decision = decide(snap(tkt()), operation, NOW)
        assert isinstance(decision, Apply) and decision.record.agent == A
