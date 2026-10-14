import pytest

pytestmark = pytest.mark.skip(reason="skeleton: ids not implemented")


def test_ticket_ids_have_prefix() -> None: ...


def test_claim_ids_are_unique() -> None: ...


def test_sequential_ids_are_deterministic() -> None: ...
