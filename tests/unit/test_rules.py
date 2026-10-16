"""Rules are pure: every transition and refusal, tested without git or real time.

The holder-op cases mirror the table in docs/design.md §5.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.unit.builders import (
    C1,
    C2,
    C3,
    LAPSED,
    NOW,
    T1,
    T2,
    T3,
    TAKEABLE,
    TTL,
    A,
    B,
    held,
    noop,
    pick,
    refused,
    snap,
    tkt,
    written,
)
from tkt_store.domain.operations import (
    AddOp,
    CancelOp,
    ClaimNextOp,
    ClaimOp,
    DoneOp,
    EditOp,
    InitOp,
    MoveOp,
    OpName,
    ReapOp,
    ReleaseOp,
    RenewOp,
)
from tkt_store.domain.outcomes import Apply, Refusal, RefusalCode
from tkt_store.domain.rules import decide
from tkt_store.domain.ticket import (
    MAX_TTL,
    AgentId,
    Claim,
    ClaimId,
    Kind,
    Phase,
    ProjectId,
    Resolution,
    Snapshot,
    Ticket,
    TicketId,
)


class TestClaim:
    def test_claims_open_ticket(self) -> None:
        decision = decide(snap(tkt()), ClaimOp(T1, A, C1, TTL), NOW)
        ticket = written(decision)
        assert ticket.claim == Claim(agent=A, claim_id=C1, lease_until=NOW + TTL, claimed_at=NOW)
        assert ticket.updated == NOW
        assert isinstance(decision, Apply) and decision.record.op is OpName.CLAIM

    def test_refuses_live_claim_by_other(self) -> None:
        decision = decide(snap(tkt(claim=held(C2, B))), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)

    def test_same_claim_id_and_agent_is_noop(self) -> None:
        decision = decide(snap(tkt(claim=held())), ClaimOp(T1, A, C1, TTL), NOW)
        assert noop(decision).ticket_ids == (T1,)

    def test_same_claim_id_and_agent_renews_a_lapsed_claim(self) -> None:
        lapsed = held(lease_until=TAKEABLE)
        ticket = written(decide(snap(tkt(claim=lapsed)), ClaimOp(T1, A, C1, TTL), NOW))
        assert ticket.claim == replace(lapsed, lease_until=NOW + TTL)

    def test_same_claim_id_other_agent_is_already_claimed(self) -> None:
        decision = decide(snap(tkt(claim=held())), ClaimOp(T1, B, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)

    def test_takes_over_expired_claim(self) -> None:
        start = tkt(claim=held(C2, B, TAKEABLE))
        ticket = written(decide(snap(start), ClaimOp(T1, A, C1, TTL), NOW))
        assert ticket.claim is not None and ticket.claim.claim_id == C1
        assert ticket.ended_claim_ids == (C2,)

    def test_refuses_blocked(self) -> None:
        decision = decide(snap(tkt(blocked_by=(T2,)), tkt(T2)), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.BLOCKED)

    def test_refuses_blocked_even_with_a_lapsed_claim(self) -> None:
        blocked = tkt(blocked_by=(T2,), claim=held(C2, B, TAKEABLE))
        refused(decide(snap(blocked, tkt(T2)), ClaimOp(T1, A, C1, TTL), NOW), RefusalCode.BLOCKED)

    def test_claim_keeps_the_phase(self) -> None:
        ticket = written(decide(snap(tkt()), ClaimOp(T1, A, C1, TTL), NOW))
        assert ticket.phase is Phase.IMPLEMENTATION

    @pytest.mark.parametrize("resolution", list(Resolution))
    def test_refuses_terminal(self, resolution: Resolution) -> None:
        decision = decide(snap(tkt(resolution=resolution)), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.TERMINAL)

    @pytest.mark.parametrize("where", ["this_ticket", "another_ticket"])
    @pytest.mark.parametrize("ending", ["release", "reap", "takeover", "cancel", "done"])
    def test_ended_claim_id_cannot_claim_again(self, ending: str, where: str) -> None:
        resolution = {"cancel": Resolution.CANCELLED, "done": Resolution.DONE}.get(ending)
        ended = tkt(T2, ended_claim_ids=(C1,), resolution=resolution)
        target = T2 if where == "this_ticket" and resolution is None else T1
        decision = decide(snap(tkt(), ended), ClaimOp(target, A, C1, TTL), NOW)
        refused(decision, RefusalCode.NOT_HOLDER)

    def test_claim_id_live_on_another_ticket_is_already_claimed(self) -> None:
        decision = decide(snap(tkt(), tkt(T2, claim=held())), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)


class TestSkewGrace:
    def test_no_takeover_within_grace(self) -> None:
        decision = decide(snap(tkt(claim=held(C2, B, LAPSED))), ClaimOp(T1, A, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)

    def test_takeover_allowed_after_grace(self) -> None:
        written(decide(snap(tkt(claim=held(C2, B, TAKEABLE))), ClaimOp(T1, A, C1, TTL), NOW))

    def test_no_reap_within_grace(self) -> None:
        noop(decide(snap(tkt(claim=held(lease_until=LAPSED))), ReapOp(), NOW))

    def test_holder_may_renew_within_grace(self) -> None:
        start = tkt(claim=held(lease_until=LAPSED))
        ticket = written(decide(snap(start), RenewOp(T1, C1, TTL), NOW))
        assert ticket.claim is not None and ticket.claim.lease_until == NOW + TTL


HOLDER_STATES = {
    "resolved": tkt(resolution=Resolution.DONE, ended_claim_ids=(C2,)),
    "cancelled": tkt(resolution=Resolution.CANCELLED),
    "done_same_claim": tkt(resolution=Resolution.DONE, ended_claim_ids=(C2, C1)),
    "done_other_claim": tkt(resolution=Resolution.DONE, ended_claim_ids=(C1, C2)),
    "current_match": tkt(claim=held()),
    "current_match_already_in_phase": tkt(claim=held(), phase=Phase.REVIEW),
    "ended_match": tkt(ended_claim_ids=(C1,)),
    "ended_match_already_in_phase": tkt(ended_claim_ids=(C1,), phase=Phase.REVIEW),
    "ended_match_other_phase": tkt(ended_claim_ids=(C1,)),
    "no_claim": tkt(),
    "other_claim": tkt(claim=held(C2, B)),
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
        decision = decide(snap(HOLDER_STATES[state]), HOLDER_OPS[op], NOW)
        if expected == "Apply":
            assert isinstance(decision, Apply), decision
        elif expected == "NoOp":
            noop(decision)
        else:
            refused(decision, RefusalCode(expected))

    def test_ended_match_wins_over_claimed_by_another(self) -> None:
        ticket = tkt(ended_claim_ids=(C1,), claim=held(C2, B))
        noop(decide(snap(ticket), ReleaseOp(T1, C1), NOW))

    def test_release_rerun_after_push_landed_is_noop(self) -> None:
        released = written(decide(snap(tkt(claim=held())), ReleaseOp(T1, C1), NOW))
        noop(decide(snap(released), ReleaseOp(T1, C1), NOW))

    def test_reaped_holder_plain_release_is_noop_with_claim_ended_reason(self) -> None:
        decision = decide(snap(tkt(ended_claim_ids=(C1,))), ReleaseOp(T1, C1), NOW)
        assert "already ended" in noop(decision).reason

    def test_reaped_holder_cannot_move_the_phase(self) -> None:
        decision = decide(snap(tkt(ended_claim_ids=(C1,))), MoveOp(T1, C1, Phase.REVIEW), NOW)
        refused(decision, RefusalCode.NOT_HOLDER)

    def test_rerun_converges_after_several_claim_cycles(self) -> None:
        noop(decide(snap(tkt(ended_claim_ids=(C1, C2, C3))), ReleaseOp(T1, C1), NOW))

    @pytest.mark.parametrize(
        ("state", "text"),
        [
            (tkt(ended_claim_ids=(C1,)), "already ended"),
            (tkt(), "never used"),
            (tkt(claim=held(C2, B)), "held by another claim"),
        ],
        ids=["already_ended", "never_used", "held_by_another"],
    )
    def test_refusal_message_says_which_case(self, state: Ticket, text: str) -> None:
        decision = decide(snap(state), RenewOp(T1, C1, TTL), NOW)
        assert isinstance(decision, Refusal) and text in decision.message

    def test_done_by_stale_holder_after_takeover(self) -> None:
        taken = tkt(claim=held(C2, B), ended_claim_ids=(C1,))
        refused(decide(snap(taken), DoneOp(T1, C1), NOW), RefusalCode.NOT_HOLDER)

    def test_done_by_stale_holder_after_completion(self) -> None:
        decision = decide(snap(HOLDER_STATES["done_other_claim"]), DoneOp(T1, C1), NOW)
        refused(decision, RefusalCode.NOT_HOLDER)

    def test_done_records_resolution_and_ended_claim(self) -> None:
        ticket = written(decide(snap(tkt(claim=held())), DoneOp(T1, C1), NOW))
        assert ticket.resolution is Resolution.DONE and ticket.claim is None
        assert ticket.ended_claim_ids == (C1,) and ticket.phase is Phase.IMPLEMENTATION

    def test_done_on_lapsed_claim_not_taken_over(self) -> None:
        written(decide(snap(tkt(claim=held(lease_until=TAKEABLE))), DoneOp(T1, C1), NOW))

    def test_done_is_not_gated_by_blockers(self) -> None:
        blocked = tkt(claim=held(), blocked_by=(T2,))
        written(decide(snap(blocked, tkt(T2)), DoneOp(T1, C1), NOW))

    @pytest.mark.parametrize("ending", ["release", "reap", "takeover", "cancel", "done"])
    def test_ending_a_claim_appends_to_ended_claim_ids(self, ending: str) -> None:
        start = tkt(claim=held(lease_until=TAKEABLE), ended_claim_ids=(C3,))
        op = pick(
            {
                "release": ReleaseOp(T1, C1),
                "reap": ReapOp(),
                "takeover": ClaimOp(T1, B, C2, TTL),
                "cancel": CancelOp(T1),
                "done": DoneOp(T1, C1),
            },
            ending,
        )
        assert written(decide(snap(start), op, NOW)).ended_claim_ids == (C3, C1)

    def test_stale_release_after_completion_is_terminal(self) -> None:
        decision = decide(snap(HOLDER_STATES["resolved"]), ReleaseOp(T1, C1), NOW)
        refused(decision, RefusalCode.TERMINAL)


class TestIdempotence:
    def test_add_same_id_same_content_is_noop(self) -> None:
        existing = tkt(created=5, updated=7)
        noop(decide(snap(existing), AddOp(T1, "Expire tokens", phase=Phase.TRIAGE), NOW))

    @pytest.mark.parametrize("since", ["move", "claim", "release", "done"])
    def test_add_rerun_after_workflow_or_occupancy_change_is_noop(self, since: str) -> None:
        changed = {
            "move": tkt(phase=Phase.REVIEW),
            "claim": tkt(claim=held()),
            "release": tkt(ended_claim_ids=(C1,)),
            "done": tkt(resolution=Resolution.DONE, ended_claim_ids=(C1,)),
        }[since]
        noop(decide(snap(changed), AddOp(T1, "Expire tokens", phase=Phase.TRIAGE), NOW))

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
        done = written(decide(snap(tkt(claim=held())), DoneOp(T1, C1), NOW))
        noop(decide(snap(done), DoneOp(T1, C1), NOW))


class TestWorkflow:
    def test_move_changes_phase_and_keeps_the_claim(self) -> None:
        decision = decide(snap(tkt(claim=held())), MoveOp(T1, C1, Phase.REVIEW), NOW)
        ticket = written(decision)
        assert ticket.phase is Phase.REVIEW and ticket.claim == held()
        assert isinstance(decision, Apply) and decision.record.phase is Phase.REVIEW

    def test_handoff_is_move_then_release(self) -> None:
        moved = written(decide(snap(tkt(claim=held())), MoveOp(T1, C1, Phase.REVIEW), NOW))
        assert moved.claim is not None
        released = written(decide(snap(moved), ReleaseOp(T1, C1), NOW))
        assert released.phase is Phase.REVIEW and released.claim is None

    def test_add_starts_unresolved_in_its_phase(self) -> None:
        ticket = written(decide(snap(), AddOp(T1, "New", phase=Phase.QA), NOW))
        assert (ticket.resolution, ticket.phase, ticket.content_version) == (None, Phase.QA, 1)
        assert ticket.created == ticket.updated == NOW

    def test_release_keeps_the_phase(self) -> None:
        ticket = written(decide(snap(tkt(claim=held())), ReleaseOp(T1, C1), NOW))
        assert ticket.phase is Phase.IMPLEMENTATION

    def test_cancel_keeps_the_phase(self) -> None:
        ticket = written(decide(snap(tkt(phase=Phase.REVIEW)), CancelOp(T1), NOW))
        assert ticket.resolution is Resolution.CANCELLED and ticket.phase is Phase.REVIEW

    def test_cancel_sets_cancelled_without_a_claim(self) -> None:
        ticket = written(decide(snap(tkt(claim=held())), CancelOp(T1), NOW))
        assert ticket.claim is None and ticket.ended_claim_ids == (C1,)

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
        "ticket_id", ["tkt-XYZ", "tkt-../x", "x/tkt-1", "tkt-", "TKT-1", "tkt-1\n"]
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
        op = pick(
            {
                "agent": ClaimOp(T1, AgentId("a\nb"), C1, TTL),
                "reason": CancelOp(T1, reason="x\ntkt-op: done"),
                "title": AddOp(T2, "line\nbreak"),
            },
            field,
        )
        refused(decide(snap(tkt()), op, NOW), RefusalCode.INVALID)

    @pytest.mark.parametrize("ttl", [0, -1, MAX_TTL + 1])
    @pytest.mark.parametrize("op", ["claim", "claim-next", "renew"])
    def test_ttl_out_of_bounds_is_invalid(self, op: str, ttl: int) -> None:
        operation = pick(
            {
                "claim": ClaimOp(T1, A, C1, ttl),
                "claim-next": ClaimNextOp(A, C1, ttl),
                "renew": RenewOp(T1, C1, ttl),
            },
            op,
        )
        refused(decide(snap(tkt(claim=held())), operation, NOW), RefusalCode.INVALID)

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

    def test_validation_wins_over_every_other_outcome(self) -> None:
        refused(decide(snap(), RenewOp(T1, ClaimId("bad"), TTL), NOW), RefusalCode.INVALID)


class TestClaimNext:
    def test_picks_highest_priority_then_oldest(self) -> None:
        tickets = snap(
            tkt(T1, priority=None, created=1),
            tkt(T2, priority=2, created=9),
            tkt(T3, priority=2, created=3),
        )
        written(decide(tickets, ClaimNextOp(A, C1, TTL), NOW), T3)

    def test_skips_blocked_and_terminal(self) -> None:
        tickets = snap(
            tkt(T1, priority=1, blocked_by=(T2,)),
            tkt(T2, priority=2, resolution=Resolution.CANCELLED),
            tkt(T3, priority=3),
        )
        written(decide(tickets, ClaimNextOp(A, C1, TTL), NOW), T3)

    def test_skips_claims_within_grace(self) -> None:
        tickets = snap(tkt(T1, priority=1, claim=held(C2, B, LAPSED)), tkt(T2, priority=2))
        written(decide(tickets, ClaimNextOp(A, C1, TTL), NOW), T2)

    def test_filters_by_project_kind_and_phase(self) -> None:
        tickets = snap(
            tkt(T1, project=ProjectId("p1"), kind=Kind.BUG, phase=Phase.REVIEW),
            tkt(T2, project=None, kind=Kind.BUG, phase=Phase.REVIEW),
        )
        op = ClaimNextOp(A, C1, TTL, project=ProjectId("p1"), kind=Kind.BUG, phase=Phase.REVIEW)
        written(decide(tickets, op, NOW), T1)

    def test_project_filter_matches_exact_value_only(self) -> None:
        decision = decide(
            snap(tkt(project=None)), ClaimNextOp(A, C1, TTL, project=ProjectId("p1")), NOW
        )
        refused(decision, RefusalCode.NOTHING_CLAIMABLE)

    def test_live_retry_is_noop_naming_the_ticket(self) -> None:
        tickets = snap(tkt(T1), tkt(T2, claim=held()))
        assert noop(decide(tickets, ClaimNextOp(A, C1, TTL), NOW)).ticket_ids == (T2,)

    def test_lapsed_retry_never_takes_a_second_ticket(self) -> None:
        tickets = snap(tkt(T1, priority=1), tkt(T2, claim=held(lease_until=TAKEABLE)))
        written(decide(tickets, ClaimNextOp(A, C1, TTL), NOW), T2)

    def test_same_claim_id_other_agent_is_already_claimed(self) -> None:
        decision = decide(snap(tkt(claim=held())), ClaimNextOp(B, C1, TTL), NOW)
        refused(decision, RefusalCode.ALREADY_CLAIMED)

    def test_ended_claim_id_is_refused(self) -> None:
        tickets = snap(tkt(), tkt(T2, ended_claim_ids=(C1,)))
        refused(decide(tickets, ClaimNextOp(A, C1, TTL), NOW), RefusalCode.NOT_HOLDER)

    def test_nothing_claimable(self) -> None:
        decision = decide(snap(tkt(resolution=Resolution.DONE)), ClaimNextOp(A, C1, TTL), NOW)
        refused(decision, RefusalCode.NOTHING_CLAIMABLE)


class TestReap:
    def test_releases_all_expired_in_one_record(self) -> None:
        tickets = snap(
            tkt(T1, claim=held(C1, A, TAKEABLE)),
            tkt(T2, claim=held(C2, B, TAKEABLE), blocked_by=(T3,)),
            tkt(T3, claim=held(C3, A)),
        )
        decision = decide(tickets, ReapOp(), NOW)
        assert isinstance(decision, Apply) and decision.record.ticket_ids == (T1, T2)
        assert written(decision, T1).ended_claim_ids == (C1,)
        assert written(decision, T2).claim is None

    def test_nothing_expired_is_noop(self) -> None:
        noop(decide(snap(tkt(claim=held())), ReapOp(), NOW))


class TestEdit:
    @pytest.mark.parametrize("state", ["missing", "resolved"])
    def test_refused_on_missing_or_terminal(self, state: str) -> None:
        tickets = snap() if state == "missing" else snap(tkt(resolution=Resolution.DONE))
        code = RefusalCode.NOT_FOUND if state == "missing" else RefusalCode.TERMINAL
        refused(decide(tickets, EditOp(T1, 1, title="X"), NOW), code)

    def test_adding_blocker_to_claimed_ticket_keeps_the_claim(self) -> None:
        tickets = snap(tkt(claim=held()), tkt(T2))
        ticket = written(decide(tickets, EditOp(T1, 1, blocked_by=(T2,)), NOW))
        assert ticket.claim == held() and ticket.blocked_by == (T2,)

    def test_unset_fields_are_unchanged(self) -> None:
        start = tkt(body="b", tags=("x",))
        ticket = written(decide(snap(start), EditOp(T1, 1, title="New"), NOW))
        assert (ticket.title, ticket.body, ticket.tags) == ("New", "b", ("x",))

    def test_priority_none_clears_it(self) -> None:
        ticket = written(decide(snap(tkt(priority=3)), EditOp(T1, 1, priority=None), NOW))
        assert ticket.priority is None

    def test_apply_increments_version(self) -> None:
        ticket = written(decide(snap(tkt(content_version=4)), EditOp(T1, 4, title="X"), NOW))
        assert ticket.content_version == 5 and ticket.updated == NOW

    def test_stale_version_is_refused(self) -> None:
        decision = decide(snap(tkt(content_version=4)), EditOp(T1, 3, title="X"), NOW)
        refused(decision, RefusalCode.STALE)

    def test_rerun_of_landed_edit_is_noop(self) -> None:
        noop(decide(snap(tkt(title="X", content_version=5)), EditOp(T1, 4, title="X"), NOW))

    def test_two_editors_same_field_second_is_stale(self) -> None:
        first = written(decide(snap(tkt(content_version=3)), EditOp(T1, 3, title="A"), NOW))
        refused(decide(snap(first), EditOp(T1, 3, title="B"), NOW), RefusalCode.STALE)

    @pytest.mark.parametrize(
        "op", ["claim", "claim-next", "renew", "move", "release", "done", "cancel", "reap"]
    )
    def test_only_edit_changes_the_version(self, op: str) -> None:
        start = tkt(content_version=3, claim=held(lease_until=TAKEABLE))
        operation = pick(
            {
                "claim": ClaimOp(T1, A, C1, TTL),
                "claim-next": ClaimNextOp(A, C1, TTL),
                "renew": RenewOp(T1, C1, TTL),
                "move": MoveOp(T1, C1, Phase.REVIEW),
                "release": ReleaseOp(T1, C1),
                "done": DoneOp(T1, C1),
                "cancel": CancelOp(T1),
                "reap": ReapOp(),
            },
            op,
        )
        assert written(decide(snap(start), operation, NOW)).content_version == 3


class TestInitAndAdd:
    def test_add_on_unborn_store_is_not_initialised(self) -> None:
        unborn = Snapshot(None, {})
        refused(decide(unborn, AddOp(T1, "T"), NOW), RefusalCode.NOT_INITIALISED)

    def test_init_on_existing_store_is_noop(self) -> None:
        noop(decide(snap(), InitOp(), NOW))
        assert isinstance(decide(Snapshot(None, {}), InitOp(), NOW), Apply)

    @pytest.mark.parametrize(
        "op", [RenewOp(T1, C1, TTL), MoveOp(T1, C1, Phase.QA), ReleaseOp(T1, C1)]
    )
    def test_every_write_sets_updated(self, op: RenewOp | MoveOp | ReleaseOp) -> None:
        assert written(decide(snap(tkt(claim=held())), op, NOW)).updated == NOW


class TestRecord:
    def test_record_carries_injected_time(self) -> None:
        decision = decide(snap(tkt(claim=held())), RenewOp(T1, C1, TTL), NOW)
        assert isinstance(decision, Apply) and decision.record.at == NOW

    @pytest.mark.parametrize("op", ["add", "edit", "cancel"])
    def test_record_carries_optional_actor(self, op: str) -> None:
        operation = pick(
            {
                "add": AddOp(T2, "T", agent=A),
                "edit": EditOp(T1, 1, title="X", agent=A),
                "cancel": CancelOp(T1, agent=A),
            },
            op,
        )
        decision = decide(snap(tkt()), operation, NOW)
        assert isinstance(decision, Apply) and decision.record.agent == A
