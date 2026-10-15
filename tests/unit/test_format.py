"""Serialisation (docs/format.md)."""

import pytest

pytestmark = pytest.mark.skip(reason="skeleton: format not implemented")


def test_ticket_round_trip_is_byte_identical() -> None: ...


def test_unknown_keys_preserved_at_top_level() -> None:
    """Unknown keys land in Ticket.extra and are written back at top level (no 'extra' key)."""


def test_done_by_round_trips() -> None: ...


def test_message_round_trip() -> None:
    """encode_message → decode_message returns an equal OpRecord, including `at`
    (tkt-time) and `stage` (tkt-stage)."""


def test_subject_is_one_line() -> None:
    """encode_message never emits a multi-line subject."""


def test_tkt_commit_without_time_is_rejected() -> None:
    """A tkt commit missing tkt-time → StoreError."""


def test_foreign_commit_decodes_to_none() -> None: ...


def test_future_protocol_version_is_rejected() -> None:
    """→ StoreError, never silently misread."""
