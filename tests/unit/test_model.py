"""Derived status (ADR 0004)."""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: model logic not implemented")


def test_status_precedence() -> None:
    """terminal stage > claim (live/expired) > blocked > open."""


def test_claim_expires_at_lease_until() -> None:
    """is_live(now) is False when now >= lease_until."""


def test_unknown_dependency_counts_as_not_done() -> None: ...


def test_sort_key_puts_none_priority_last() -> None: ...
