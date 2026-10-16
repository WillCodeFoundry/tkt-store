"""A remote given as a file path: every agent that can push can also write the remote's
repository directory, including its hooks and config."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.security import design
from tests.security.conftest import service
from tests.unit.builders import T2

pytestmark = pytest.mark.git


@design("a hook planted in a path remote runs inside the next honest agent's push")
@pytest.mark.parametrize("hook", ["pre-receive", "update", "post-receive"])
def test_a_hook_planted_in_a_path_remote_does_not_run_in_honest_agents(
    clone: Path, bare_remote: Path, tmp_path: Path, hook: str
) -> None:
    marker = tmp_path / f"ran-{hook}"
    planted = bare_remote / "hooks" / hook
    planted.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 0\n')
    planted.chmod(0o755)
    service(clone).add("Honest work", ticket_id=T2)
    assert not marker.exists()
