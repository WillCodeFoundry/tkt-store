# Contributing

The rules for working on tkt-store: where each kind of change is specified, tooling,
checks, tests and commits. To set up a clone, follow *Prerequisites* and *Getting
started* in the [README](../README.md).

## Where changes are specified

Read the document for your change before making it. If code and its document disagree,
one of them is wrong: fix it, or amend the document in the same change, never silently.

| Change | Specified in |
|---|---|
| What tkt-store promises, and how it keeps that using state-store | [`tkt-store/README.md`](tkt-store/README.md), [`tkt-store/design.md`](tkt-store/design.md) (both TBD) |
| What state-store promises: its interface, guarantees, errors, keys | [`state-store/README.md`](state-store/README.md) |
| How state-store keeps those promises on git | [`state-store/design.md`](state-store/design.md) |
| A decision: why something is the way it is | [`state-store/decisions/`](state-store/decisions/README.md), or [`tkt-store/decisions/`](tkt-store/decisions/README.md) (none yet); see *Decision records* below |

## Decision records

A decision record says what was decided, why, and what was rejected; the specification
and design documents say what is. tkt-store and state-store each keep their own, in
their `decisions/` directory.

- Its title is the decision as a short instruction ("Use …", "Store …"), and its file
  name is the number and the title, in lowercase with hyphens:
  `0003-store-values-as-files-on-one-git-branch.md`. Number it in sequence within its
  directory, and add it to that directory's index.
- A decision is never edited to say something else: a later one supersedes it, and both
  say so in their status.
- Update the specification or design the decision changes in the same change.

Every record has this shape:

```markdown
# NNNN: The decision, as a short instruction

**Status:** proposed | accepted | superseded by NNNN

## Context
What forces the decision: the problem, the constraints, what is known.

## Decision
What was decided, stated plainly.

## Alternatives rejected
Each option considered and not taken, with the reason.

## Consequences
What follows from the decision, good and bad, and what it rules out.
```

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
- The repository root is a uv workspace with no package of its own: each package under
  `src/` is a member with its own `pyproject.toml`, and the root `pyproject.toml` holds
  the dev tools and tool settings they share.
- Every tool's version is pinned once, in the `dev` group of the root `pyproject.toml`;
  the hooks and CI run it with `uv run`.
- `uv.lock` is tracked and CI installs from it exactly (`uv sync --locked`). Commit it
  whenever dependencies change; refresh versions deliberately with `uv lock --upgrade`.
- A weekly CI job (`latest-deps`) runs the whole suite on every supported Python
  against the newest allowed versions, ignoring the lockfile.

## Checks

**They run themselves:** just commit and push. Locally, the checks are the hooks in
`.pre-commit-config.yaml`, in two stages:

- **pre-commit** (on `git commit`): ruff format, ruff check, mypy, and the tests that
  need no git;
- **pre-push** (on `git push`): the whole test suite.

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

General rules:

- Use dependency injection with fakes (such as `MemoryStateStore`). Do not
  `monkeypatch` or `mock.patch` internals; setting the environment variables a test
  needs is fine.
- Behaviour that involves git is tested against real git, marked `@pytest.mark.git`.
- Test modules read on their own: constants and small builders are defined where used.
- Each package's tests live in `src/<package>/tests/`. That directory has no
  `__init__.py` (so no package named `tests` can clash between packages); its modules
  are top-level names, so give new ones names that cannot clash.

For state-store (`src/state-store`):

- Every behaviour both stores share is tested in `tests/test_contract.py`, against
  `MemoryStateStore` and `GitStateStore` alike, so they keep identical semantics; what
  only git has is in `tests/test_git.py`, against real git.
- Its tests import shared helpers from `tests/state_store_testkit.py` only.
- Only `state_store/runner.py` starts processes (git); the package uses the standard
  library only.
- While it is a skeleton, every test of unimplemented behaviour is a strict expected
  failure (`xfail(raises=NotImplementedError, strict=True)`); implementing a part
  removes the marker from its tests.

## Commits

Commits are signed and carry no co-author trailers. Never use `--no-verify`.

For Claude Code, installing the git hooks is required, not optional: its hook refuses
every commit and push until they are. It also enforces this policy: it blocks a commit
that carries a `Co-Authored-By` trailer, uses `--no-gpg-sign` or would be unsigned, and
any commit or push with `--no-verify`.
