# AGENTS.md

Rules for agents (and humans) working on this repository.

The repository is being rebuilt from the bottom up. Earlier code, docs and decisions
were removed (they remain in git history on `main`) and come back only when a layer
needs them. Today it holds one package, **state-store**.

## Layout and authorities

| Path | What |
|---|---|
| `docs/` | All documentation. Each component has a doc that is its authority. |
| `src/<package>/` | One package per directory, each a uv workspace member with its own `pyproject.toml`. |
| `src/<package>/tests/` | That package's tests. |

A component's doc is the authority on what it promises and how. If code and doc
disagree, one of them is wrong: fix it, or amend the doc in the same change. Never
deviate silently. Read the doc before changing the component.

## state-store (`src/state-store`, imported as `state_store`)

A key/value store on a git branch: snapshot reads, all-or-nothing commits by
compare-and-swap. Authorities: `docs/state-store.md` (what it promises) and
`docs/state-store-design.md` (how it maps onto git).

- Only `state_store/runner.py` starts processes (git). The package uses the standard
  library only.
- Every behaviour both stores share is tested in `tests/test_contract.py`, against
  `MemoryStateStore` and `GitStateStore` alike, so they keep identical semantics.
  What only git has is in `tests/test_git.py`, against real git.
- Its tests import shared helpers from `tests/state_store_testkit.py` only. The tests
  directory has no `__init__.py` (so no package named `tests` can clash between
  packages); its modules are top-level names, so give new ones names that cannot clash.
- While it is a skeleton, every test of unimplemented behaviour is a strict expected
  failure (`xfail(raises=NotImplementedError, strict=True)`); implementing a part
  removes the marker from its tests.

## Testing

- Use dependency injection with fakes (such as `MemoryStateStore`). Do not
  `monkeypatch` or `mock.patch` internals; setting environment variables a test needs
  is fine.
- Behaviour that involves git is tested against real git, marked `@pytest.mark.git`.
- Test modules read on their own: constants and small builders are defined where used.

## Tooling

Use `uv` for everything: `uv sync --group dev` to set up (dev tools are an opt-in
group; a plain `uv sync` installs none), `uv add` / `uv add --dev` to change
dependencies, `uv run <tool>` to run tools. Never use `pip` or `pip install`.

The root `pyproject.toml` is a uv workspace with no package of its own: it lists the
members and holds the dev tools and tool settings they share.

`uv.lock` is tracked and CI installs from it exactly (`uv sync --locked`). Commit it
whenever dependencies change; refresh versions deliberately with `uv lock --upgrade`.
A weekly CI job (`latest-deps`) runs the tests on every supported Python against the
newest allowed versions, ignoring the lockfile.

## Before committing

Run these explicitly; they must pass (they are what CI runs):

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

pytest is quiet and strict about markers by default (`addopts = "-q --strict-markers"`
in `pyproject.toml`); use `-vv` to list individual tests.

Two hooks back this up; they are a safety net, not the check:

- `pre-commit` (`.pre-commit-config.yaml`, all `repo: local` hooks run via `uv run`, so
  no version is pinned outside the `dev` group) installs as two git hook types with
  `uv run pre-commit install --hook-type pre-commit --hook-type pre-push`:
  - **pre-commit**: ruff format, ruff check, mypy and the tests that need no git
    (`pytest -m "not git"`);
  - **pre-push**: the whole suite (`uv run pytest`), as CI's test job runs it.

  Do not invoke pre-commit directly in place of the commands above.
- For Claude Code, `.claude/hooks/pre-commit-checks.sh` blocks any `git commit` that
  carries a `Co-Authored-By` trailer, uses `--no-verify` or `--no-gpg-sign`, or would
  be unsigned, and runs the four commands above first.

Commits are signed and carry no co-author trailers. Never use `--no-verify`.
Every tool's version is pinned once, in the `dev` group of `pyproject.toml`.
