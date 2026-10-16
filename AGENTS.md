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
- `cli` imports `application` (and `domain` types) + the composition root (`__init__`:
  `open_store`, `new_id_source`); never `infrastructure`.
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
Exception: before 1.0, any format change made while no store is deployed may keep
`PROTOCOL_VERSION` when documented in `docs/format.md`.

## Tooling

Use `uv` for everything: `uv sync --group dev` to set up (dev tools are an opt-in
group; a plain `uv sync` installs none), `uv add` / `uv add --dev` to change
dependencies, `uv run <tool>` to run tools. Never use `pip` or `pip install`.

`uv.lock` is tracked and CI installs from it exactly (`uv sync --locked`). Commit it
whenever dependencies change; refresh versions deliberately with `uv lock --upgrade`.
It pins only the development environment: consumers of the package resolve from
`pyproject.toml`. A small weekly CI job (`latest-deps`) runs the fast tests on every
supported Python against the newest allowed versions, ignoring the lockfile.

## Before committing

Run these explicitly; they must pass (they are what CI runs):

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

pytest is quiet by default (`addopts = "-q"` in `pyproject.toml`); use `-vv` to list
individual tests.

Two hooks back this up; they are a safety net, not the check:

- The pre-commit hooks (installed with `uv run pre-commit install`) run a subset of
  these on every `git commit`. Do not invoke pre-commit directly in place of the
  commands above.
- For Claude Code, `.claude/hooks/pre-commit-checks.sh` blocks any `git commit` that
  carries a `Co-Authored-By` trailer, uses `--no-verify` or `--no-gpg-sign`, or would
  be unsigned, and runs the four commands above first.

Commits are signed and carry no co-author trailers. Never use `--no-verify`.
The ruff version is pinned in `pyproject.toml` and `.pre-commit-config.yaml`; change both together.
