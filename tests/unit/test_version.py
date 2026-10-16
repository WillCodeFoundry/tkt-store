"""The package version is stated twice; they must agree."""

from __future__ import annotations

import tomllib
from pathlib import Path

import tkt_store

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    assert tkt_store.__version__ == project["version"]
