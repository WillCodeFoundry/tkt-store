"""Serialisation (docs/format.md)."""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: format not implemented")


def test_ticket_round_trip_is_byte_identical() -> None: ...


def test_unknown_keys_preserved_in_extra() -> None: ...


def test_message_round_trip() -> None:
    """encode_message → decode_message returns an equal OpRecord."""


def test_foreign_commit_decodes_to_none() -> None: ...


def test_future_protocol_version_is_rejected() -> None:
    """→ StoreError, never silently misread."""
