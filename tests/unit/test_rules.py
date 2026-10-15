"""Rules are pure: every transition and refusal, tested without git or real time.

SKELETON: each test documents the behaviour to implement. The holder-op cases mirror
the table in docs/design.md §5.
"""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: rules not implemented")


class TestClaim:
    def test_claims_open_ticket(self) -> None:
        """OPEN + ClaimOp → Apply; claim = (agent, claim_id, lease_until = now + ttl,
        claimed_at = now); updated = now; op='claim'."""

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
        new claim; ended_claim_id = the old claim id, which is now fenced."""

    def test_refuses_blocked(self) -> None:
        """A blocker that is not yet done → Refusal(BLOCKED)."""

    def test_refuses_blocked_even_with_a_lapsed_claim(self) -> None:
        """Blocked + claim past the grace → Refusal(BLOCKED), not a takeover."""

    def test_refuses_terminal(self) -> None:
        """Resolved (done/cancelled) → Refusal(TERMINAL)."""

    @pytest.mark.parametrize("where", ["this_ticket", "another_ticket"])
    @pytest.mark.parametrize("ending", ["release", "reap", "takeover", "cancel", "done"])
    def test_ended_claim_id_cannot_claim_again(self, ending: str, where: str) -> None:
        """op.claim_id equals any ticket's ended_claim_id → Refusal(NOT_HOLDER)."""

    def test_claim_id_live_on_another_ticket_is_already_claimed(self) -> None:
        """One claim id names one claim on one ticket → Refusal(ALREADY_CLAIMED)."""


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
            ("renew", "resolved", "TERMINAL"),
            ("release", "resolved", "TERMINAL"),
            ("done", "cancelled", "TERMINAL"),
            ("done", "done_same_claim", "NoOp"),
            ("done", "done_other_claim", "NOT_HOLDER"),
            ("renew", "current_match", "Apply"),
            ("release", "current_match", "Apply"),
            ("done", "current_match", "Apply"),
            ("renew", "ended_match", "NOT_HOLDER"),
            ("release", "ended_match_same_phase", "NoOp"),
            ("release", "ended_match_other_phase", "NOT_HOLDER"),
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
        """A released, then B claims; A re-runs release → NoOp (step 3 before step 5)."""

    def test_release_rerun_after_push_landed_is_noop(self) -> None:
        """The release landed (ended_claim_id = c1) but was retried → NoOp."""

    def test_reaped_holder_plain_release_is_noop_with_claim_ended_reason(self) -> None: ...

    def test_reaped_holder_cannot_move_the_phase(self) -> None:
        """Reaped holder's release --to-phase X, ticket not at X → Refusal(NOT_HOLDER)."""

    def test_done_by_stale_holder_after_takeover(self) -> None:
        """A claims, lease lapses past the grace, B claims, A sends DoneOp →
        Refusal(NOT_HOLDER)."""

    def test_done_records_resolution_and_ended_claim(self) -> None:
        """DoneOp → Apply: resolution=DONE, ended_claim_id=op.claim_id, claim=None, phase
        kept."""

    def test_done_is_not_gated_by_blockers(self) -> None:
        """A blocker added after the claim does not refuse done."""

    @pytest.mark.parametrize("ending", ["release", "reap", "takeover", "cancel", "done"])
    def test_ending_a_claim_sets_ended_claim_id(self, ending: str) -> None: ...


class TestIdempotence:
    def test_add_same_id_same_content_is_noop(self) -> None:
        """Only AddOp fields are compared; created/updated differ on a later re-run."""

    def test_add_rerun_after_update_is_duplicate_id(self) -> None: ...

    def test_add_same_id_different_content_is_refused(self) -> None:
        """→ Refusal(DUPLICATE_ID)."""

    def test_done_twice_is_noop(self) -> None:
        """A second DoneOp by the same claim (resolution DONE, claim_id == ended_claim_id)
        → NoOp."""


class TestWorkflow:
    def test_release_hands_off_to_phase(self) -> None:
        """ReleaseOp(to_phase=review) → Apply: claim cleared, phase=review,
        record.phase=review, ended_claim_id=op.claim_id."""

    def test_add_starts_unresolved_in_its_phase(self) -> None:
        """AddOp(phase=P) → resolution None, phase P, content_version 1."""

    def test_cancel_keeps_the_phase(self) -> None:
        """Cancelling a ticket in review → resolution cancelled, phase still review."""

    def test_cancel_sets_cancelled_without_a_claim(self) -> None: ...

    def test_cancel_done_ticket_is_terminal(self) -> None: ...

    def test_cancel_twice_is_noop(self) -> None: ...

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
        """Empty title, unknown or self blocker, dependency cycle → Refusal(INVALID)."""

    def test_validation_wins_over_every_other_outcome(self) -> None:
        """A malformed op on a missing or terminal ticket → Refusal(INVALID), not
        NOT_FOUND/TERMINAL."""

    @pytest.mark.parametrize("expected_version", [0, -1])
    def test_bad_expected_version_is_invalid(self, expected_version: int) -> None:
        """UpdateOp.expected_version < 1 → Refusal(INVALID)."""


class TestClaimNext:
    def test_picks_highest_priority_then_oldest(self) -> None: ...

    def test_skips_blocked_and_terminal(self) -> None: ...

    def test_skips_claims_within_grace(self) -> None:
        """A lapsed claim within SKEW_GRACE is not a candidate (claimable is False)."""

    def test_filters_by_project_kind_and_phase(self) -> None: ...

    def test_lapsed_retry_never_takes_a_second_ticket(self) -> None:
        """Same claim_id and agent hold a lapsed (not taken over) claim → NoOp naming it."""

    def test_ended_claim_id_is_refused(self) -> None:
        """op.claim_id equals any ticket's ended_claim_id → Refusal(NOT_HOLDER)."""

    def test_same_claim_id_other_agent_is_already_claimed(self) -> None: ...

    def test_project_filter_matches_exact_value_only(self) -> None:
        """--project X never matches a ticket whose project is null."""

    def test_nothing_claimable(self) -> None:
        """→ Refusal(NOTHING_CLAIMABLE)."""


class TestReap:
    def test_releases_all_expired_in_one_record(self) -> None:
        """Every claim past the grace, blocked or not, in one record; each reaped claim id
        becomes that ticket's ended_claim_id."""

    def test_nothing_expired_is_noop(self) -> None:
        """None past the grace period → NoOp."""


class TestUpdate:
    @pytest.mark.parametrize("state", ["missing", "resolved"])
    def test_refused_on_missing_or_terminal(self, state: str) -> None:
        """NOT_FOUND / TERMINAL."""

    def test_adding_blocker_to_claimed_ticket_keeps_the_claim(self) -> None: ...

    def test_unset_fields_are_unchanged(self) -> None: ...

    def test_priority_none_clears_it(self) -> None:
        """UpdateOp(priority=None) → Apply with priority=None (UNSET would leave it)."""

    def test_apply_increments_version(self) -> None:
        """expected_version == content_version → Apply with content_version + 1."""

    def test_stale_version_is_refused(self) -> None:
        """Ticket updated since it was read (content_version != expected_version) and the op
        changes something → Refusal(STALE); nothing is overwritten."""

    def test_rerun_of_landed_update_is_noop(self) -> None:
        """Fields already hold the op's values → NoOp, even though content_version moved
        on (the NoOp check comes before the version check)."""

    def test_two_editors_same_field_second_is_stale(self) -> None:
        """A and B both read content_version 3 and set the title; A lands (4), B →
        Refusal(STALE) — never last-writer-wins."""

    @pytest.mark.parametrize(
        "op", ["claim", "claim-next", "renew", "release", "done", "cancel", "reap"]
    )
    def test_only_update_changes_the_version(self, op: str) -> None:
        """Every op except add (sets 1) and update (+1) leaves content_version unchanged, so a
        holder's renewals never make an editor's update STALE."""


class TestInitAndAdd:
    def test_add_on_unborn_store_is_not_initialised(self) -> None: ...

    def test_init_on_existing_store_is_noop(self) -> None: ...

    def test_every_write_sets_updated(self) -> None:
        """Each Apply sets updated = now on every ticket it writes."""


class TestRecord:
    def test_record_carries_injected_time(self) -> None:
        """Every Apply.record has at == now."""

    @pytest.mark.parametrize("op", ["add", "update", "cancel"])
    def test_record_carries_optional_actor(self, op: str) -> None:
        """op.agent, when given, is record.agent (tkt-agent); omitted otherwise."""
