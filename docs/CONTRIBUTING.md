# Contributing

The rules for working on tkt-store: where each kind of change is specified, tooling,
checks, tests and commits. To set up a clone, follow *Prerequisites* and *Getting
started* in the [README](../README.md).

## Where changes are specified

Read the document for your change before making it: [`README.md`](README.md) in this
directory maps them. If code and its document disagree, one of them is wrong: fix it, or
amend the document in the same change, never silently.

## Writing documentation

- **One home per fact.** State each fact once, in the document that owns it, and link
  to it from anywhere else. Repeated facts drift apart.
- **Stay in scope.** A document describes its own component only. state-store's
  documents, code and tests never mention tkt-store or any program or kind of user that
  relies on it: state-store is general-purpose, and its documents stay true whoever uses
  it. tkt-store's documents may refer to state-store.
- **Introduce a term before using it.**
- **Say what is, plainly.** Short sentences, concrete words, the fact first. No emphasis
  words ("crucially", "robust", "seamless"), no dramatic framing ("not X, but Y"), no
  closing summaries that repeat what was just said.
- **Decision records** follow the template below. They give the forces behind a
  decision as they stand, never the history of earlier designs, and record decisions
  about the system, not about naming or wording. Each rejected choice and each
  consequence appears in one record only.

## Decision records

A decision record says what was decided, why, and what was rejected; the specification
and design documents say what is. tkt-store and state-store each keep their own, in
their `decisions/` directory.

- Its title is the decision as a short instruction ("Use …", "Store …"), and its file
  name is the number and the title, in lowercase with hyphens:
  `0002-store-keys-as-paths-in-the-tree-of-one-git-branch.md`. Number it in sequence
  within its directory, and add it to that directory's index.
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

This project uses [uv](https://docs.astral.sh/uv/) for environments, dependencies,
running tools and the Python version (`.python-version`, which uv fetches if it is
missing). Do not use `pip`.

- `uv sync --group dev` sets up (dev tools are an opt-in group), `uv add` /
  `uv add --dev` change dependencies, `uv run <tool>` runs a tool.
- The repository root is a uv workspace with no package of its own: each package under
  `src/` is a member with its own `pyproject.toml`, and the root `pyproject.toml` holds
  the dev tools and tool settings they share.
- Every tool has a minimum version in the `dev` group of the root `pyproject.toml`, and
  an exact version in `uv.lock`; the hooks and CI run it with `uv run`.
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
`always_run: true`: ruff also formats Python inside Markdown, and `pyproject.toml`
configures every tool), and names its stage. CI's actions are pinned to commit SHAs,
kept current by Dependabot. Local runs and CI use the same Python
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
- Tests come with the code they cover, in the same change. The contract tests, written
  ahead of the implementation, are strict expected failures
  (`xfail(raises=NotImplementedError, strict=True)`) until the part they test exists;
  implementing it removes the marker.

## Commits

Commits are signed and carry no co-author trailers. Never use `--no-verify`.

For Claude Code, installing the git hooks is required, not optional: its hook refuses
every commit and push until they are. It also enforces this policy: it blocks a commit
that carries a `Co-Authored-By` trailer, uses `--no-gpg-sign` or would be unsigned, and
any commit or push with `--no-verify`.
