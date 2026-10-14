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


def _imports(source: str, rel_parts: tuple[str, ...]) -> tuple[list[tuple[str, ...]], set[str]]:
    """Return (internal dotted paths after the package, top-level external module names).

    Resolves relative imports against the module's package, and treats each name in
    `from tkt_store import X` as a target of its own (a submodule or a root re-export).
    """
    tree = ast.parse(source)
    internal: list[tuple[str, ...]] = []
    external: set[str] = set()
    package = rel_parts[:-1]  # the package a module's relative imports start from
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == PACKAGE:
                    internal.append(tuple(parts[1:]) or ("__init__",))
                else:
                    external.add(parts[0])
        elif isinstance(node, ast.ImportFrom):
            module = tuple(node.module.split(".")) if node.module else ()
            if node.level == 0:
                if module[0] == "__future__":
                    continue
                if module[0] != PACKAGE:
                    external.add(module[0])
                    continue
                base = module[1:]
            else:
                up = node.level - 1
                assert up <= len(package), f"relative import escapes the package: {rel_parts}"
                base = package[: len(package) - up] + module
            if node.module and base:
                internal.append(base)
            else:  # `from <package> import X`: each X is a submodule or a re-export
                internal.extend((*base, alias.name) for alias in node.names)
    return internal, external


def _violations(layer: str, internal: list[tuple[str, ...]]) -> list[str]:
    allowed = ALLOWED_INWARD[layer]
    return [
        f"imports {'.'.join(parts)} ({target}); allowed: {sorted(allowed)}"
        for parts in internal
        if (target := _import_layer(parts)) not in allowed
    ]


def _modules() -> dict[str, tuple[str, tuple[str, ...], list[tuple[str, ...]], set[str]]]:
    """name -> (layer, rel_parts, internal imports, external imports)."""
    out: dict[str, tuple[str, tuple[str, ...], list[tuple[str, ...]], set[str]]] = {}
    for p in SRC.rglob("*.py"):
        rel_parts = p.relative_to(SRC).parts
        name = "/".join(rel_parts)
        internal, external = _imports(p.read_text(), rel_parts)
        out[name] = (_layer_of(rel_parts), rel_parts, internal, external)
    return out


MODULES = _modules()


def test_package_found() -> None:
    assert MODULES, f"no modules found under {SRC}"


@pytest.mark.parametrize("name", sorted(MODULES))
def test_inward_only_dependencies(name: str) -> None:
    layer, _, internal, _ = MODULES[name]
    assert not _violations(layer, internal), f"{name} ({layer}): {_violations(layer, internal)}"


@pytest.mark.parametrize(
    "source",
    [
        "from ..infrastructure import memory",
        "from ..infrastructure.memory import MemStore",
        "from .. import open_store",
        "from tkt_store import GitStore",
        "from tkt_store import infrastructure",
        "import tkt_store",
    ],
)
def test_classifier_catches_indirect_outward_imports(source: str) -> None:
    """Regression: relative and package-root imports used to escape the checks."""
    rel_parts = (DOMAIN, "synthetic.py")
    internal, _ = _imports(source, rel_parts)
    assert _violations(_layer_of(rel_parts), internal), f"not caught: {source}"


def test_classifier_allows_relative_imports_within_a_layer() -> None:
    internal, _ = _imports("from .ticket import Ticket\nfrom . import status", (DOMAIN, "x.py"))
    assert internal == [(DOMAIN, "ticket"), (DOMAIN, "status")]
    assert not _violations(DOMAIN, internal)


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
