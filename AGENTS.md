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
- Security findings live in `tests/security/` as strict expected failures, marked
  `@pytest.mark.security_bug(reason)` (a defect) or `security_design(reason)` (needs a
  decision). A fix removes its marker; a new finding gets its failing test first. The
  model they test: ADR 0005 and `docs/design.md` §8.
- Test modules read on their own: constants and small builders are defined where used.
  The only module tests import from `tests/` is `tests/gitkit.py` (real-git machinery).

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
`pyproject.toml`. A weekly CI job (`latest-deps`) runs the whole suite on every
supported Python against the newest allowed versions, ignoring the lockfile.

## Checks

The checks are defined once, as hooks in `.pre-commit-config.yaml`, in two stages:

- **pre-commit**: ruff format, ruff check, mypy, and the tests that need no git;
- **pre-push**: the whole test suite.

Everything runs those hooks the way git's own hooks do (`pre-commit run`, plus
`--hook-stage pre-push` for that stage, and no file arguments, so what is checked is
what is staged) rather than its own copy of the commands:

| Who | Runs |
|---|---|
| git, once hooks are installed (`uv run pre-commit install --hook-type pre-commit --hook-type pre-push`) | each stage on commit and on push |
| the Claude Code hook (`.claude/hooks/pre-commit-checks.sh`) | the same stage before a `git commit` or `git push`, unless git's own hook for it is pre-commit's (then git runs it, so it never runs twice) |
| CI (`.github/workflows/ci.yml`) | one job per hook, listed from `.pre-commit-config.yaml` when CI runs |
| you, to check work without committing | `uv run pre-commit run`, and `uv run pre-commit run --hook-stage pre-push` for the whole suite |

To add or change a check, change `.pre-commit-config.yaml` and nothing else: CI gives a
new hook its own job by itself. Give every hook a `stages` entry. Local runs and CI use
the same Python (`.python-version`, the requires-python floor).

pytest is quiet and strict about markers by default (`addopts = "-q --strict-markers"`
in `pyproject.toml`); to see individual tests, run pytest itself with `-vv`.

The Claude Code hook also enforces the commit policy: it blocks a commit that carries a
`Co-Authored-By` trailer, uses `--no-gpg-sign` or would be unsigned, and any commit or
push with `--no-verify`.

Commits are signed and carry no co-author trailers. Never use `--no-verify`.
Every tool's version is pinned once, in the `dev` group of `pyproject.toml`.
