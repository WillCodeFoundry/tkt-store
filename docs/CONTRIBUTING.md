# Contributing

The rules for working on tkt-store: tooling, checks, tests and commits. To set up a
clone, follow *Getting started* in the [README](../README.md). What the code must do is
in [`design.md`](design.md), the authority on concepts, boundaries and invariants: if
code and design disagree, one of them is wrong, so fix it or amend the design in the
same change, never silently.

## Setup details

The README's setup ends with `uv run pre-commit install`, which installs both git hooks
(`pre-commit` and `pre-push`, from `default_install_hook_types` in
`.pre-commit-config.yaml`); check with `ls .git/hooks/pre-commit .git/hooks/pre-push`.
It refuses to install if git's `core.hooksPath` is set: unset it, or point it at a
directory that runs these hooks. A plain `uv sync` (without `--group dev`) installs none
of the dev tools, so the hooks would fail.

## Tooling

This project uses [uv](https://docs.astral.sh/uv/) for environments, dependencies and
running tools. Do not use `pip`.

- `uv sync --group dev` sets up (dev tools are an opt-in group), `uv add` /
  `uv add --dev` change dependencies, `uv run <tool>` runs a tool.
- Every tool's version is pinned once, in the `dev` group of `pyproject.toml`; the
  hooks and CI run it with `uv run`.
- `uv.lock` is tracked and CI installs from it exactly (`uv sync --locked`). Commit it
  whenever dependencies change; refresh versions deliberately with `uv lock --upgrade`.
  It pins only the development environment: consumers of the package resolve from
  `pyproject.toml`.
- A weekly CI job (`latest-deps`) runs the whole suite on every supported Python
  against the newest allowed versions, ignoring the lockfile.

## Checks

**They run themselves:** just commit and push. Locally, the checks are the hooks in
`.pre-commit-config.yaml`, in two stages:

- **pre-commit** (on `git commit`, about 8 s): ruff format, ruff check, mypy, and the
  tests that need no git;
- **pre-push** (on `git push`, about a minute): the whole test suite.

A failing check stops the commit or push and says why. There is no need to run them
first: that only runs them twice.

| Who | Runs |
|---|---|
| git, once hooks are installed | each stage on commit and on push |
| the Claude Code hook (`.claude/hooks/pre-commit-checks.sh`) | nothing: it blocks a `git commit` or `git push` unless git's hook for that stage is pre-commit's, so the checks always run through git, once |
| CI (`.github/workflows/ci.yml`) | the same commands, directly with `uv run`: one job per tool (`ruff`, `mypy`, `test`) |
| you, to check work without committing (what is staged, as a commit would) | `uv run pre-commit run`, and `uv run pre-commit run --hook-stage pre-push` for the whole suite |

To change a check, change it in both `.pre-commit-config.yaml` and `ci.yml`. Every hook
checks the whole repository and runs whatever changed (`pass_filenames: false`,
`always_run: true`), and names its stage. Local runs and CI use the same Python
(`.python-version`, the requires-python floor).

pytest is quiet and strict about markers by default (`addopts = "-q --strict-markers"`
in `pyproject.toml`); to see individual tests, run pytest itself with `-vv`.

## Testing

- Use dependency injection with fakes (`MemStore`, `FakeClock`, a fixed id source). Do
  not `monkeypatch` or `mock.patch` internals.
- Any change to store behaviour must be expressed in `tests/contract/` so both stores
  keep identical semantics.
- Race and crash behaviour is tested against real git (`tests/integration/`).
- Security findings live in `tests/security/` as strict expected failures, marked
  `@pytest.mark.security_bug(reason)` (a defect) or `security_design(reason)` (needs a
  decision). A fix removes its marker; a new finding gets its failing test first. The
  model they test: ADR 0005 and [`design.md`](design.md) §8.
- Test modules read on their own: constants and small builders are defined where used.
  The only module tests import from `tests/` is `tests/gitkit.py` (real-git machinery).
- The layer boundaries of [`design.md`](design.md) §3 are enforced by
  `tests/unit/test_architecture.py`.

## Commits

Commits are signed and carry no co-author trailers. Never use `--no-verify`.

For Claude Code, installing the git hooks is required, not optional: its hook refuses
every commit and push until they are. It also enforces this policy: it blocks a commit
that carries a `Co-Authored-By` trailer, uses `--no-gpg-sign` or would be unsigned, and
any commit or push with `--no-verify`.
