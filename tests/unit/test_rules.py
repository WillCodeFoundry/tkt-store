"""Rules are pure: every transition and refusal, tested without git or real time.

SKELETON: each test documents the behaviour to implement. The holder-op cases mirror
the table in docs/design.md §5.
"""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: rules not implemented")


class TestClaim:
    def test_claims_open_ticket(self) -> None:
        """OPEN + ClaimOp → Apply; claim = (agent, claim_id, now + ttl); op='claim'."""

    def test_refuses_live_claim_by_other(self) -> None:
        """Live claim with a different claim_id → Refusal(ALREADY_CLAIMED)."""

    def test_same_claim_id_and_agent_is_noop(self) -> None:
        """Current claim with the same claim_id and agent → NoOp naming the ticket."""

    def test_same_claim_id_and_agent_is_noop_even_when_lapsed(self) -> None:
        """Lapsed (not taken over) claim with the same claim_id and agent → NoOp."""

    def test_same_claim_id_other_agent_is_already_claimed(self) -> None:
        """Current claim has op.claim_id but another agent → Refusal(ALREADY_CLAIMED)."""

    def test_takes_over_expired_claim(self) -> None:
        """Claim lapsed past SKEW_GRACE (now >= lease_until + SKEW_GRACE) → Apply with the
        new claim; last_claim_id = the old claim id, which is now fenced."""

    def test_refuses_blocked(self) -> None:
        """A blocker that is not yet done → Refusal(BLOCKED)."""

    def test_refuses_blocked_even_with_a_lapsed_claim(self) -> None:
        """Blocked + claim past the grace → Refusal(BLOCKED), not a takeover."""

    def test_refuses_terminal(self) -> None:
        """done/cancelled → Refusal(TERMINAL)."""

    @pytest.mark.parametrize("field", ["last_claim_id", "done_by"])
    def test_ended_claim_id_cannot_claim_again(self, field: str) -> None:
        """op.claim_id equals the ticket's last_claim_id or done_by → Refusal(NOT_HOLDER)."""


class TestSkewGrace:
    def test_no_takeover_within_grace(self) -> None:
        """lease_until <= now < lease_until + SKEW_GRACE → Refusal(ALREADY_CLAIMED)."""

    def test_takeover_allowed_after_grace(self) -> None:
        """now == lease_until + SKEW_GRACE → Apply (takeover)."""

    def test_no_reap_within_grace(self) -> None:
        """Only claims lapsed within the grace → NoOp."""

    def test_holder_may_renew_within_grace(self) -> None:
        """Lapsed but not taken over: the matching claim_id renews → Apply."""


class TestHolderOps:
    """docs/design.md §5, holder-op table, checked in the documented order."""

    @pytest.mark.parametrize(
        ("op", "state", "expected"),
        [
            ("renew", "terminal", "TERMINAL"),
            ("release", "terminal", "TERMINAL"),
            ("done", "cancelled", "TERMINAL"),
            ("done", "done_by_same", "NoOp"),
            ("done", "done_by_other", "NOT_HOLDER"),
            ("renew", "current_match", "Apply"),
            ("release", "current_match", "Apply"),
            ("done", "current_match", "Apply"),
            ("renew", "ended_match", "NOT_HOLDER"),
            ("release", "ended_match_same_stage", "NoOp"),
            ("release", "ended_match_other_stage", "NOT_HOLDER"),
            ("done", "ended_match", "NOT_HOLDER"),
            ("renew", "no_claim", "NOT_CLAIMED"),
            ("release", "no_claim", "NOT_CLAIMED"),
            ("done", "no_claim", "NOT_CLAIMED"),
            ("renew", "other_claim", "NOT_HOLDER"),
            ("release", "other_claim", "NOT_HOLDER"),
            ("done", "other_claim", "NOT_HOLDER"),
        ],
    )
    def test_table(self, op: str, state: str, expected: str) -> None:
        """Each (op, ticket state) cell gives the documented outcome."""

    def test_ended_match_wins_over_claimed_by_another(self) -> None:
        """A released, then B claims; A re-runs release → NoOp (step 4 before step 6)."""

    def test_release_rerun_after_push_landed_is_noop(self) -> None:
        """The release landed (last_claim_id = c1) but was retried → NoOp."""

    def test_reaped_holder_plain_release_is_noop_with_claim_ended_reason(self) -> None: ...

    def test_reaped_holder_cannot_move_the_stage(self) -> None:
        """Reaped holder's release --to-stage X, ticket not at X → Refusal(NOT_HOLDER)."""

    def test_done_by_stale_holder_after_takeover(self) -> None:
        """A claims, lease lapses past the grace, B claims, A sends DoneOp →
        Refusal(NOT_HOLDER)."""

    def test_done_records_done_by(self) -> None:
        """DoneOp → Apply: stage=DONE, done_by=op.claim_id, claim=None."""

    def test_done_is_not_gated_by_blockers(self) -> None:
        """A blocker added after the claim does not refuse done."""

    @pytest.mark.parametrize("ending", ["release", "reap", "takeover", "cancel"])
    def test_ending_a_claim_sets_last_claim_id(self, ending: str) -> None: ...


class TestIdempotence:
    def test_add_same_id_same_content_is_noop(self) -> None:
        """Only AddOp fields are compared; created/updated differ on a later re-run."""

    def test_add_rerun_after_update_is_duplicate_id(self) -> None: ...

    def test_add_same_id_different_content_is_refused(self) -> None:
        """→ Refusal(DUPLICATE_ID)."""

    def test_done_twice_is_noop(self) -> None:
        """A second DoneOp by the same claim (claim_id == done_by) → NoOp."""


class TestStage:
    def test_release_hands_off_to_stage(self) -> None:
        """ReleaseOp(to_stage=review) → Apply: claim cleared, stage=review,
        record.stage=review, last_claim_id=op.claim_id."""

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

    @pytest.mark.parametrize("claim_id", ["0", "abc", "A" * 32, "0" * 31, "0" * 33])
    def test_bad_claim_id_is_invalid(self, claim_id: str) -> None:
        """claim_id not exactly 32 lowercase hex characters → Refusal(INVALID)."""

    @pytest.mark.parametrize("field", ["agent", "reason", "title"])
    def test_control_characters_are_invalid(self, field: str) -> None:
        """A newline (or other control character) in the field → Refusal(INVALID)."""

    @pytest.mark.parametrize("ttl", [0, -1, 24 * 60 * 60 + 1])
    @pytest.mark.parametrize("op", ["claim", "claim-next", "renew"])
    def test_ttl_out_of_bounds_is_invalid(self, op: str, ttl: int) -> None:
        """ttl <= 0 or ttl > MAX_TTL → Refusal(INVALID), for every op with a ttl."""

    def test_update_validates_like_add(self) -> None:
        """Empty title, unknown or self blocker → Refusal(INVALID)."""

    @pytest.mark.parametrize("expected_version", [0, -1])
    def test_bad_expected_version_is_invalid(self, expected_version: int) -> None:
        """UpdateOp.expected_version < 1 → Refusal(INVALID)."""


class TestClaimNext:
    def test_picks_highest_priority_then_oldest(self) -> None: ...

    def test_skips_blocked_and_terminal(self) -> None: ...

    def test_skips_claims_within_grace(self) -> None:
        """A lapsed claim within SKEW_GRACE is not a candidate (claimable is False)."""

    def test_filters_by_project_kind_and_stage(self) -> None: ...

    def test_lapsed_retry_never_takes_a_second_ticket(self) -> None:
        """Same claim_id and agent hold a lapsed (not taken over) claim → NoOp naming it."""

    def test_ended_claim_id_is_refused(self) -> None:
        """op.claim_id equals any ticket's last_claim_id or done_by → Refusal(NOT_HOLDER)."""

    def test_nothing_claimable(self) -> None:
        """→ Refusal(NOTHING_CLAIMABLE)."""


class TestReap:
    def test_releases_all_expired_in_one_record(self) -> None:
        """Every claim past the grace, blocked or not, in one record; each reaped claim id
        becomes that ticket's last_claim_id."""

    def test_nothing_expired_is_noop(self) -> None:
        """None past the grace period → NoOp."""


class TestUpdate:
    def test_unset_fields_are_unchanged(self) -> None: ...

    def test_priority_none_clears_it(self) -> None:
        """UpdateOp(priority=None) → Apply with priority=None (UNSET would leave it)."""

    def test_apply_increments_version(self) -> None:
        """expected_version == ticket.version → Apply with version + 1."""

    def test_stale_version_is_refused(self) -> None:
        """Ticket updated since it was read (version != expected_version) and the op
        changes something → Refusal(STALE); nothing is overwritten."""

    def test_rerun_of_landed_update_is_noop(self) -> None:
        """Fields already hold the op's values → NoOp, even though version moved on
        (the NoOp check comes before the version check)."""

    def test_two_editors_same_field_second_is_stale(self) -> None:
        """A and B both read version 3 and set the title; A lands (version 4), B →
        Refusal(STALE) — never last-writer-wins."""

    @pytest.mark.parametrize(
        "op", ["claim", "claim-next", "renew", "release", "done", "cancel", "reap"]
    )
    def test_only_update_changes_the_version(self, op: str) -> None:
        """Every op except add (sets 1) and update (+1) leaves version unchanged, so a
        holder's renewals never make an editor's update STALE."""


class TestRecord:
    def test_record_carries_injected_time(self) -> None:
        """Every Apply.record has at == now."""

    @pytest.mark.parametrize("op", ["add", "update", "cancel"])
    def test_record_carries_optional_actor(self, op: str) -> None:
        """op.agent, when given, is record.agent (tkt-agent); omitted otherwise."""
