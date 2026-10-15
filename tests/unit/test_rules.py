"""Rules are pure: every transition and refusal, tested without git or real time.

SKELETON: each test documents the behaviour to implement.
"""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: rules not implemented")


class TestClaim:
    def test_claims_open_ticket(self) -> None:
        """OPEN + ClaimOp → Apply; claim = (agent, claim_id, now + ttl); op='claim'."""

    def test_refuses_live_claim_by_other(self) -> None:
        """Live claim with a different claim_id → Refusal(ALREADY_CLAIMED)."""

    def test_same_claim_id_is_noop(self) -> None:
        """Live claim with the same claim_id → NoOp (retry after success)."""

    def test_takes_over_expired_claim(self) -> None:
        """Claim lapsed past SKEW_GRACE (now >= lease_until + SKEW_GRACE) → Apply with the
        new claim; old claim_id is now fenced."""

    def test_refuses_blocked(self) -> None:
        """A blocker that is not yet done → Refusal(BLOCKED)."""

    def test_refuses_blocked_even_with_a_lapsed_claim(self) -> None:
        """Blocked + claim past the grace → Refusal(BLOCKED), not a takeover."""

    def test_refuses_terminal(self) -> None:
        """done/cancelled → Refusal(TERMINAL)."""

    def test_refuses_non_positive_ttl(self) -> None:
        """ttl <= 0 → Refusal(INVALID)."""


class TestSkewGrace:
    def test_no_takeover_within_grace(self) -> None:
        """lease_until <= now < lease_until + SKEW_GRACE → Refusal(ALREADY_CLAIMED)."""

    def test_takeover_allowed_after_grace(self) -> None:
        """now == lease_until + SKEW_GRACE → Apply (takeover)."""

    def test_no_reap_within_grace(self) -> None:
        """Only claims lapsed within the grace → NoOp."""

    def test_holder_may_renew_within_grace(self) -> None:
        """Lapsed but not taken over: the matching claim_id renews → Apply."""


class TestFencing:
    def test_renew_with_wrong_claim_id(self) -> None:
        """→ Refusal(NOT_HOLDER)."""

    def test_done_by_stale_holder_after_takeover(self) -> None:
        """A claims, lease lapses past the grace, B claims, A sends DoneOp →
        Refusal(NOT_HOLDER)."""

    def test_done_by_stale_holder_after_completion(self) -> None:
        """B completes (closed_by = B), then stale A sends DoneOp → Refusal(NOT_HOLDER),
        not NoOp."""

    def test_done_records_closed_by(self) -> None:
        """DoneOp → Apply: stage=DONE, closed_by=op.claim_id, claim=None."""

    def test_done_on_lapsed_claim_not_taken_over(self) -> None:
        """Matching claim_id on an expired claim nobody took over → Apply."""

    def test_release_with_wrong_claim_id(self) -> None:
        """→ Refusal(NOT_HOLDER)."""

    def test_stale_release_after_completion_is_terminal(self) -> None:
        """ReleaseOp on a done/cancelled ticket → Refusal(TERMINAL), checked before the
        unclaimed NoOp."""


class TestIdempotence:
    def test_add_same_id_same_content_is_noop(self) -> None: ...

    def test_add_same_id_different_content_is_refused(self) -> None:
        """→ Refusal(DUPLICATE_ID)."""

    def test_done_twice_is_noop(self) -> None:
        """A second DoneOp by the same claim (claim_id == closed_by) → NoOp."""

    def test_release_when_unclaimed_is_noop(self) -> None:
        """No to_stage, ticket already unclaimed and non-terminal → NoOp."""


class TestStage:
    def test_release_hands_off_to_stage(self) -> None:
        """ReleaseOp(to_stage=review) → Apply: claim cleared, stage=review,
        record.stage=review."""

    def test_handoff_rerun_is_noop(self) -> None:
        """Re-running release --to-stage review on the unclaimed ticket now at review → NoOp."""

    def test_handoff_by_fenced_agent_is_refused(self) -> None:
        """Unclaimed ticket, to_stage differs from the current stage → Refusal(NOT_HOLDER)."""

    def test_release_to_terminal_stage_is_refused(self) -> None:
        """to_stage in {done, cancelled} → Refusal(INVALID); use done/cancel."""

    def test_add_in_terminal_stage_is_refused(self) -> None:
        """AddOp(stage=done|cancelled) → Refusal(INVALID)."""

    def test_cancel_sets_cancelled_without_a_claim(self) -> None: ...

    def test_cancelled_blocker_does_not_satisfy_dependency(self) -> None:
        """A dependent of a cancelled ticket stays BLOCKED; only a done blocker clears it."""


class TestValidation:
    @pytest.mark.parametrize("ticket_id", ["tkt-XYZ", "tkt-../x", "x/tkt-1", "tkt-", "TKT-1"])
    def test_bad_ticket_id_is_invalid(self, ticket_id: str) -> None:
        """As op.ticket_id or a blocked_by entry → Refusal(INVALID)."""

    def test_bad_claim_id_is_invalid(self) -> None:
        """claim_id not matching ^[0-9a-f]+$ → Refusal(INVALID)."""

    @pytest.mark.parametrize("field", ["agent", "reason", "title"])
    def test_control_characters_are_invalid(self, field: str) -> None:
        """A newline (or other control character) in the field → Refusal(INVALID)."""

    def test_update_validates_like_add(self) -> None:
        """Empty title, unknown or self blocker → Refusal(INVALID)."""


class TestClaimNext:
    def test_picks_highest_priority_then_oldest(self) -> None: ...

    def test_skips_blocked_and_terminal(self) -> None: ...

    def test_skips_claims_within_grace(self) -> None:
        """A lapsed claim within SKEW_GRACE is not a candidate (claimable is False)."""

    def test_filters_by_project_kind_and_stage(self) -> None: ...

    def test_nothing_claimable(self) -> None:
        """→ Refusal(NOTHING_CLAIMABLE)."""


class TestReap:
    def test_releases_all_expired_in_one_record(self) -> None:
        """Every claim past the grace, blocked or not, in one record."""

    def test_nothing_expired_is_noop(self) -> None:
        """None past the grace period → NoOp."""


class TestRecord:
    def test_record_carries_injected_time(self) -> None:
        """Every Apply.record has at == now."""
