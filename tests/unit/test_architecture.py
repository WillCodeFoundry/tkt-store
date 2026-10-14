"""Layer boundary rules from docs/design.md §3. This test is REAL (not a skeleton).

It parses every module's imports (including imports inside functions) and
enforces inward-only dependencies plus the three "only here" rules:

Layers, outermost last:
    domain  <-  application  <-  infrastructure
                            <-  cli            (the interface)
    __init__ / __main__                        (the composition root)

- domain imports domain only.
- application imports domain + application.
- infrastructure imports domain + application + infrastructure.
- cli imports domain + application + the composition root (never infrastructure).
- the composition root (__init__) may import anything.

"Only here" rules:
- git / subprocess only under infrastructure/git/.
- the system clock (time/datetime) only in infrastructure/clock.py.
- randomness (random/secrets/uuid) only in infrastructure/ids.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = "tkt_store"
SRC = Path(__file__).resolve().parents[2] / "src" / PACKAGE

DOMAIN, APPLICATION, INFRASTRUCTURE, INTERFACE, ROOT = (
    "domain",
    "application",
    "infrastructure",
    "interface",
    "root",
)

# Which layers each layer is allowed to import from (always including itself).
ALLOWED_INWARD = {
    DOMAIN: {DOMAIN},
    APPLICATION: {DOMAIN, APPLICATION},
    INFRASTRUCTURE: {DOMAIN, APPLICATION, INFRASTRUCTURE},
    INTERFACE: {DOMAIN, APPLICATION, ROOT},
    ROOT: {DOMAIN, APPLICATION, INFRASTRUCTURE, INTERFACE, ROOT},
}

ROOT_STEMS = {"__init__", "__main__"}

SUBPROCESS = {"subprocess"}
TIME_MODULES = {"time", "datetime"}
RANDOM_MODULES = {"random", "secrets", "uuid"}
IO_MODULES = {"os", "io", "pathlib", "shutil", "tempfile", "socket"}


def _layer_of(rel_parts: tuple[str, ...]) -> str:
    """Classify a module (given its path parts relative to the package) into a layer."""
    head = rel_parts[0]
    if head in (DOMAIN, APPLICATION, INFRASTRUCTURE):
        return head
    stem = rel_parts[-1].removesuffix(".py")
    if stem == "cli":
        return INTERFACE
    if stem in ROOT_STEMS:
        return ROOT
    raise AssertionError(f"unclassified module: {'/'.join(rel_parts)}")


def _import_layer(internal_parts: tuple[str, ...]) -> str:
    """The layer an internal import (parts after `tkt_store.`) belongs to."""
    head = internal_parts[0]
    if head in (DOMAIN, APPLICATION, INFRASTRUCTURE):
        return head
    if head == "cli":
        return INTERFACE
    return ROOT  # factory, or a top-level re-export


def _imports(path: Path) -> tuple[list[tuple[str, ...]], set[str]]:
    """Return (internal dotted paths after the package, top-level external module names)."""
    tree = ast.parse(path.read_text(), filename=str(path))
    internal: list[tuple[str, ...]] = []
    external: set[str] = set()
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            if name == "__future__":
                continue
            parts = name.split(".")
            if parts[0] == PACKAGE:
                if len(parts) > 1:
                    internal.append(tuple(parts[1:]))
            else:
                external.add(parts[0])
    return internal, external


def _modules() -> dict[str, tuple[str, tuple[str, ...], list[tuple[str, ...]], set[str]]]:
    """name -> (layer, rel_parts, internal imports, external imports)."""
    out: dict[str, tuple[str, tuple[str, ...], list[tuple[str, ...]], set[str]]] = {}
    for p in SRC.rglob("*.py"):
        rel_parts = p.relative_to(SRC).parts
        name = "/".join(rel_parts)
        internal, external = _imports(p)
        out[name] = (_layer_of(rel_parts), rel_parts, internal, external)
    return out


MODULES = _modules()


def test_package_found() -> None:
    assert MODULES, f"no modules found under {SRC}"


@pytest.mark.parametrize("name", sorted(MODULES))
def test_inward_only_dependencies(name: str) -> None:
    layer, _, internal, _ = MODULES[name]
    allowed = ALLOWED_INWARD[layer]
    for parts in internal:
        target = _import_layer(parts)
        assert target in allowed, (
            f"{name} ({layer}) imports {'.'.join(parts)} ({target}); allowed: {sorted(allowed)}"
        )


@pytest.mark.parametrize("name", sorted(MODULES))
def test_subprocess_only_in_git_adapter(name: str) -> None:
    _, rel_parts, _, external = MODULES[name]
    under_git = rel_parts[:2] == (INFRASTRUCTURE, "git")
    if not under_git:
        assert not external & SUBPROCESS, f"{name} must not run git/subprocess"


@pytest.mark.parametrize("name", sorted(MODULES))
def test_domain_is_pure(name: str) -> None:
    layer, _, _, external = MODULES[name]
    if layer != DOMAIN:
        return
    forbidden = external & (SUBPROCESS | TIME_MODULES | RANDOM_MODULES | IO_MODULES)
    assert not forbidden, f"domain module {name} imports {forbidden}"


@pytest.mark.parametrize("name", sorted(MODULES))
def test_time_and_randomness_are_injected(name: str) -> None:
    _, rel_parts, _, external = MODULES[name]
    is_clock = rel_parts == (INFRASTRUCTURE, "clock.py")
    is_ids = rel_parts == (INFRASTRUCTURE, "ids.py")
    if not is_clock:
        assert not external & TIME_MODULES, f"{name} reads the system clock directly"
    if not is_ids:
        assert not external & RANDOM_MODULES, f"{name} creates randomness directly"
