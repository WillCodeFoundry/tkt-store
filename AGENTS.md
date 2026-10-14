# AGENTS.md

Rules for agents (and humans) working on this repository.

Read `docs/design.md` first. It is the authority on concepts, boundaries and
invariants. If code and design disagree, one of them is wrong: fix it, or amend
the design in the same change. Never deviate silently.

## Boundaries (enforced by `tests/unit/test_architecture.py`)

Dependencies point **inward only**: `domain` ← `application` ← `infrastructure`,
`domain` ← `application` ← `cli`, and `__init__` (the composition root) wires them together.

- `domain/*` is **pure**: no IO, no git, no clock reads, no randomness. It imports
  only from within `domain`.
- `application/*` imports `domain` and `application` only. It defines the ports
  (`Store`, `Clock`, `IdSource`); it must not import `infrastructure`.
- `infrastructure/*` implements the ports. Only modules under `infrastructure/git/`
  run `git`; only `infrastructure/clock.py` reads time; only `infrastructure/ids.py`
  creates random values.
- `cli` imports `application` (and `domain` types) + the `open_store` composition root
  (`__init__`); never `infrastructure`.
- The transaction loop depends on the `Store` port, never on a concrete store.
- Choosing concrete implementations happens in exactly one place: `tkt_store.open_store`
  (in `__init__`).

## Testing

- Use dependency injection with fakes (`MemStore`, `FakeClock`, a fixed id source).
  Do not `monkeypatch` or `mock.patch` internals.
- Any change to store behaviour must be expressed in `tests/contract/` so both
  stores keep identical semantics.
- Race and crash behaviour is tested against real git (`tests/integration/`).

## Format changes

Any change to the on-branch format bumps `PROTOCOL_VERSION` in
`infrastructure/git/wire.py` and updates `docs/format.md` in the same change.
Exception: pre-1.0 format additions that no deployed store relies on may keep
`PROTOCOL_VERSION` when documented in `docs/format.md`.

## Tooling

Use `uv` for everything: `uv sync` to set up, `uv add` / `uv add --dev` to change
dependencies, `uv run <tool>` to run tools. Never use `pip` or `pip install`.

## Before committing

These must pass (they are what CI runs):

```sh
uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q
```

`uv run pre-commit run --all-files` runs the same tools as hooks. Never use `--no-verify`.
The ruff version is pinned in `pyproject.toml` and `.pre-commit-config.yaml`; change both together.
