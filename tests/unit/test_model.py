"""Derived status (ADR 0004)."""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: model logic not implemented")


def test_status_precedence() -> None:
    """terminal stage > claimed (live) > blocked > expired > open."""


def test_blocked_with_lapsed_claim_reads_blocked() -> None:
    """Not EXPIRED: blocked outranks a lapsed claim."""


def test_claim_expires_at_lease_until() -> None:
    """is_live(now) is False when now >= lease_until."""


def test_claim_takeable_only_after_grace() -> None:
    """is_takeable(now) is False before lease_until + SKEW_GRACE, True from it."""


def test_claimable_is_false_within_grace() -> None:
    """A claim lapsed within SKEW_GRACE reads EXPIRED but claimable() is False."""


def test_claimable_is_false_when_blocked() -> None: ...


@pytest.mark.parametrize("state", ["terminal", "blocked", "live", "in_grace"])
def test_why_not_claimable_gives_the_refusal(state: str) -> None:
    """TERMINAL, BLOCKED, ALREADY_CLAIMED (live and in-grace); None when claimable."""


def test_claim_age_is_since_claimed_at() -> None:
    """Claim.age(now) == now - claimed_at; renew does not reset claimed_at."""


def test_unknown_dependency_counts_as_not_done() -> None: ...


def test_sort_key_puts_none_priority_last() -> None: ...
