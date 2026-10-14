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
        """Expired claim → Apply with the new claim; old claim_id is now fenced."""

    def test_refuses_blocked(self) -> None:
        """A blocker that is not yet done → Refusal(BLOCKED)."""

    def test_refuses_terminal(self) -> None:
        """done/cancelled → Refusal(TERMINAL)."""

    def test_refuses_non_positive_ttl(self) -> None:
        """ttl <= 0 → Refusal(INVALID)."""


class TestFencing:
    def test_renew_with_wrong_claim_id(self) -> None:
        """→ Refusal(NOT_HOLDER)."""

    def test_done_by_stale_holder_after_takeover(self) -> None:
        """A claims, lease expires, B claims, A sends DoneOp → Refusal(NOT_HOLDER)."""

    def test_release_with_wrong_claim_id(self) -> None:
        """→ Refusal(NOT_HOLDER)."""


class TestIdempotence:
    def test_add_same_id_same_content_is_noop(self) -> None: ...

    def test_add_same_id_different_content_is_refused(self) -> None:
        """→ Refusal(DUPLICATE_ID)."""

    def test_done_twice_is_noop(self) -> None: ...

    def test_release_when_unclaimed_is_noop(self) -> None: ...


class TestStage:
    def test_release_hands_off_to_stage(self) -> None:
        """ReleaseOp(to_stage=review) → Apply: claim cleared, stage=review."""

    def test_release_to_terminal_stage_is_refused(self) -> None:
        """to_stage in {done, cancelled} → Refusal(INVALID); use done/cancel."""

    def test_cancel_sets_cancelled_without_a_claim(self) -> None: ...

    def test_cancelled_blocker_does_not_satisfy_dependency(self) -> None:
        """A dependent of a cancelled ticket stays BLOCKED; only a done blocker clears it."""


class TestClaimNext:
    def test_picks_highest_priority_then_oldest(self) -> None: ...

    def test_skips_blocked_and_terminal(self) -> None: ...

    def test_filters_by_project_kind_and_stage(self) -> None: ...

    def test_nothing_claimable(self) -> None:
        """→ Refusal(NOTHING_CLAIMABLE)."""


class TestReap:
    def test_releases_all_expired_in_one_record(self) -> None: ...

    def test_nothing_expired_is_noop(self) -> None: ...
