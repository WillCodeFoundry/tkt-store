"""The TicketStore facade: id minting and what failures carry (docs/design.md §6)."""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: service not implemented")


def test_add_remints_on_duplicate_id_when_minted() -> None:
    """A minted id collides → re-mint and retry; the outcome names the final id."""


def test_add_with_supplied_id_never_retries() -> None:
    """Supplied ticket_id → DUPLICATE_ID or NoOp is returned as-is."""


def test_failures_carry_the_last_ids_tried() -> None:
    """RetriesExhausted / StoreError .op holds the ids of the last attempt."""


def test_edit_with_stale_expected_version_is_stale() -> None:
    """A stale expected_version → Refused(STALE)."""


def test_view_and_list_read_one_snapshot() -> None:
    """view/list return ticket and status from the same snapshot (one fetch)."""
