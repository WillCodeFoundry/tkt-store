"""CLI end-to-end against a temporary store (docs/cli.md)."""

import pytest

pytestmark = [pytest.mark.git, pytest.mark.skip(reason="skeleton")]


def test_add_claim_done_flow_with_json_output() -> None: ...


def test_exit_codes_match_docs() -> None:
    """0 committed/unchanged, 1 refused, 2 usage, 3 retries exhausted, 4 store error."""
