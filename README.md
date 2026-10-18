# tkt-store

A ticket store for coordinating AI agents, kept on a git branch.

> **Status: being rebuilt from the bottom up.** The previous implementation (release
> 0.1.0) is on `main`. This branch starts again with a smaller design, one layer at a
> time; earlier code and docs come back only when a layer needs them.

## Layers

| Package | What | Docs |
|---|---|---|
| `src/state-store` (`state_store`) | A key/value store on a git branch: snapshot reads, all-or-nothing commits that land only if nothing changed since the snapshot. Skeleton: interface, docs and tests; no implementation yet. | [`docs/state-store.md`](docs/state-store.md), [`docs/state-store-design.md`](docs/state-store-design.md) |

The ticket layer, built on state-store, comes next.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environments,
dependencies and running tools. Do not use `pip`. The repository root is a uv
workspace; each package under `src/` is a member.

**Set up a clone for development** (once per clone). You need uv and git 2.29 or later;
uv fetches a suitable Python (3.11 or later) if you have none.

```sh
git clone https://github.com/WillCodeFoundry/tkt-store.git
cd tkt-store
uv sync --group dev    # .venv from uv.lock, with the dev tools (they are opt-in)
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

The last command installs both git hooks; check with `ls .git/hooks/pre-commit
.git/hooks/pre-push`. It refuses to install if git's `core.hooksPath` is set: unset it,
or point it at a directory that runs these hooks. A plain `uv sync` installs none of the
dev tools, so the hooks would fail.

**Checks run themselves:** just commit and push. On `git commit` the hooks run ruff,
mypy and the tests that need no git; on `git push`, the whole suite, as CI's test job
runs it. A failing check stops the commit or push and says why.

To check work without committing, run the same commands CI runs:

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

Every tool's version is pinned once, in the `dev` group of `pyproject.toml`; the hooks
run it with `uv run`. `uv.lock` is tracked; commit it whenever dependencies change. See
`AGENTS.md` for the commit rules and the Claude Code hook.
