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
        """Live current claim with the same claim_id and agent → NoOp naming the ticket."""

    def test_same_claim_id_and_agent_renews_a_lapsed_claim(self) -> None:
        """Lapsed (not taken over) claim with the same claim_id and agent → Apply:
        lease_until = now + ttl, claimed_at unchanged."""

    def test_same_claim_id_other_agent_is_already_claimed(self) -> None:
        """Current claim has op.claim_id but another agent → Refusal(ALREADY_CLAIMED)."""

    def test_takes_over_expired_claim(self) -> None:
        """Claim lapsed past SKEW_GRACE (now >= lease_until + SKEW_GRACE) → Apply with the
        new claim; the old claim id is appended to ended_claim_ids and fenced."""

    def test_refuses_blocked(self) -> None:
        """A blocker that is not yet done → Refusal(BLOCKED)."""

    def test_refuses_blocked_even_with_a_lapsed_claim(self) -> None:
        """Blocked + claim past the grace → Refusal(BLOCKED), not a takeover."""

    def test_claim_keeps_the_phase(self) -> None:
        """A claim never moves the phase."""

    def test_refuses_terminal(self) -> None:
        """Resolved (done/cancelled) → Refusal(TERMINAL)."""

    @pytest.mark.parametrize("where", ["this_ticket", "another_ticket"])
    @pytest.mark.parametrize("ending", ["release", "reap", "takeover", "cancel", "done"])
    def test_ended_claim_id_cannot_claim_again(self, ending: str, where: str) -> None:
        """op.claim_id in any ticket's ended_claim_ids → Refusal(NOT_HOLDER)."""

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
        """Each (op, ticket state) cell gives the documented outcome."""

    def test_ended_match_wins_over_claimed_by_another(self) -> None:
        """A released, then B claims; A re-runs release → NoOp (step 3 before step 5)."""

    def test_release_rerun_after_push_landed_is_noop(self) -> None:
        """The release landed (c1 in ended_claim_ids) but was retried → NoOp."""

    def test_reaped_holder_plain_release_is_noop_with_claim_ended_reason(self) -> None: ...

    def test_reaped_holder_cannot_move_the_phase(self) -> None:
        """Reaped holder's move --to-phase X, ticket not at X → Refusal(NOT_HOLDER)."""

    def test_rerun_converges_after_several_claim_cycles(self) -> None:
        """A's release lands; B and C each claim and release; A re-runs → NoOp (A's id is
        still in ended_claim_ids)."""

    @pytest.mark.parametrize("case", ["already_ended", "never_used", "held_by_another"])
    def test_refusal_message_says_which_case(self, case: str) -> None: ...

    def test_done_by_stale_holder_after_takeover(self) -> None:
        """A claims, lease lapses past the grace, B claims, A sends DoneOp →
        Refusal(NOT_HOLDER)."""

    def test_done_records_resolution_and_ended_claim(self) -> None:
        """DoneOp → Apply: resolution=DONE, op.claim_id appended to ended_claim_ids,
        claim=None, phase kept."""

    def test_done_is_not_gated_by_blockers(self) -> None:
        """A blocker added after the claim does not refuse done."""

    @pytest.mark.parametrize("ending", ["release", "reap", "takeover", "cancel", "done"])
    def test_ending_a_claim_appends_to_ended_claim_ids(self, ending: str) -> None: ...


class TestIdempotence:
    def test_add_same_id_same_content_is_noop(self) -> None:
        """Identity and content are compared; created/updated differ on a later re-run."""

    @pytest.mark.parametrize("since", ["move", "claim", "release", "done"])
    def test_add_rerun_after_workflow_or_occupancy_change_is_noop(self, since: str) -> None:
        """phase, resolution and claims are never compared."""

    def test_add_rerun_after_edit_is_noop(self) -> None:
        """content_version > 1 and same kind/project → NoOp."""

    @pytest.mark.parametrize("field", ["kind", "project"])
    def test_add_with_different_identity_is_duplicate_id(self, field: str) -> None: ...

    def test_add_same_id_different_content_is_refused(self) -> None:
        """Never edited (content_version == 1) and content differs → DUPLICATE_ID."""

    def test_done_twice_is_noop(self) -> None:
        """A second DoneOp by the same claim (resolution DONE, claim_id is the last of
        ended_claim_ids) → NoOp."""


class TestWorkflow:
    def test_move_changes_phase_and_keeps_the_claim(self) -> None:
        """MoveOp(to_phase=review) → Apply: phase=review, record.phase=review, claim kept."""

    def test_handoff_is_move_then_release(self) -> None:
        """Move then release: the ticket ends unheld in the new phase; between the two it
        is held in the new phase."""

    def test_add_starts_unresolved_in_its_phase(self) -> None:
        """AddOp(phase=P) → resolution None, phase P, content_version 1."""

    def test_release_keeps_the_phase(self) -> None: ...

    def test_cancel_keeps_the_phase(self) -> None:
        """Cancelling a ticket in review → resolution cancelled, phase still review."""

    def test_cancel_sets_cancelled_without_a_claim(self) -> None: ...

    def test_cancel_done_ticket_is_terminal(self) -> None: ...

    def test_cancel_twice_is_noop(self) -> None: ...

    def test_cancelled_blocker_does_not_satisfy_dependency(self) -> None:
        """A dependent of a cancelled ticket stays BLOCKED; only a done blocker clears it."""


class TestValidation:
    @pytest.mark.parametrize(
        "ticket_id", ["tkt-XYZ", "tkt-../x", "x/tkt-1", "tkt-", "TKT-1", "tkt-1\n"]
    )
    def test_bad_ticket_id_is_invalid(self, ticket_id: str) -> None:
        """As op.ticket_id or a blocked_by entry → Refusal(INVALID)."""

    @pytest.mark.parametrize(
        "claim_id", ["0", "abc", "A" * 32, "0" * 31, "0" * 33, "0" * 32 + "\n"]
    )
    def test_bad_claim_id_is_invalid(self, claim_id: str) -> None:
        """claim_id not exactly 32 lowercase hex characters → Refusal(INVALID)."""

    @pytest.mark.parametrize("field", ["agent", "reason", "title"])
    def test_control_characters_are_invalid(self, field: str) -> None:
        """A newline (or other control character) in the field → Refusal(INVALID)."""

    @pytest.mark.parametrize("ttl", [0, -1, 2 * 60 * 60 + 1])
    @pytest.mark.parametrize("op", ["claim", "claim-next", "renew"])
    def test_ttl_out_of_bounds_is_invalid(self, op: str, ttl: int) -> None:
        """ttl <= 0 or ttl > MAX_TTL → Refusal(INVALID), for every op with a ttl."""

    def test_edit_validates_like_add(self) -> None:
        """Empty title, unknown or self blocker, dependency cycle → Refusal(INVALID)."""

    def test_validation_wins_over_every_other_outcome(self) -> None:
        """A malformed op on a missing or terminal ticket → Refusal(INVALID), not
        NOT_FOUND/TERMINAL."""

    @pytest.mark.parametrize("expected_version", [0, -1])
    def test_bad_expected_version_is_invalid(self, expected_version: int) -> None:
        """EditOp.expected_version < 1 → Refusal(INVALID)."""


class TestClaimNext:
    def test_picks_highest_priority_then_oldest(self) -> None: ...

    def test_skips_blocked_and_terminal(self) -> None: ...

    def test_skips_claims_within_grace(self) -> None:
        """A lapsed claim within SKEW_GRACE is not a candidate (claimable is False)."""

    def test_filters_by_project_kind_and_phase(self) -> None: ...

    def test_live_retry_is_noop_naming_the_ticket(self) -> None:
        """Same claim_id and agent hold a live claim on some ticket → NoOp naming it."""

    def test_lapsed_retry_never_takes_a_second_ticket(self) -> None:
        """Same claim_id and agent hold a lapsed (not taken over) claim → renew it on that
        ticket, never claim a second one."""

    def test_ended_claim_id_is_refused(self) -> None:
        """op.claim_id in any ticket's ended_claim_ids → Refusal(NOT_HOLDER)."""

    def test_same_claim_id_other_agent_is_already_claimed(self) -> None: ...

    def test_project_filter_matches_exact_value_only(self) -> None:
        """--project X never matches a ticket whose project is null."""

    def test_nothing_claimable(self) -> None:
        """→ Refusal(NOTHING_CLAIMABLE)."""


class TestReap:
    def test_releases_all_expired_in_one_record(self) -> None:
        """Every claim past the grace, blocked or not, in one record; each reaped claim id
        is appended to that ticket's ended_claim_ids."""

    def test_nothing_expired_is_noop(self) -> None:
        """None past the grace period → NoOp."""


class TestEdit:
    @pytest.mark.parametrize("state", ["missing", "resolved"])
    def test_refused_on_missing_or_terminal(self, state: str) -> None:
        """NOT_FOUND / TERMINAL."""

    def test_adding_blocker_to_claimed_ticket_keeps_the_claim(self) -> None: ...

    def test_unset_fields_are_unchanged(self) -> None: ...

    def test_priority_none_clears_it(self) -> None:
        """EditOp(priority=None) → Apply with priority=None (UNSET would leave it)."""

    def test_apply_increments_version(self) -> None:
        """expected_version == content_version → Apply with content_version + 1."""

    def test_stale_version_is_refused(self) -> None:
        """Ticket updated since it was read (content_version != expected_version) and the op
        changes something → Refusal(STALE); nothing is overwritten."""

    def test_rerun_of_landed_edit_is_noop(self) -> None:
        """Fields already hold the op's values → NoOp, even though content_version moved
        on (the NoOp check comes before the version check)."""

    def test_two_editors_same_field_second_is_stale(self) -> None:
        """A and B both read content_version 3 and set the title; A lands (4), B →
        Refusal(STALE) — never last-writer-wins."""

    @pytest.mark.parametrize(
        "op", ["claim", "claim-next", "renew", "move", "release", "done", "cancel", "reap"]
    )
    def test_only_edit_changes_the_version(self, op: str) -> None:
        """Every op except add (sets 1) and edit (+1) leaves content_version unchanged, so a
        holder's renewals never make an editor's edit STALE."""


class TestInitAndAdd:
    def test_add_on_unborn_store_is_not_initialised(self) -> None: ...

    def test_init_on_existing_store_is_noop(self) -> None: ...

    def test_every_write_sets_updated(self) -> None:
        """Each Apply sets updated = now on every ticket it writes."""


class TestRecord:
    def test_record_carries_injected_time(self) -> None:
        """Every Apply.record has at == now."""

    @pytest.mark.parametrize("op", ["add", "edit", "cancel"])
    def test_record_carries_optional_actor(self, op: str) -> None:
        """op.agent, when given, is record.agent (tkt-agent); omitted otherwise."""
