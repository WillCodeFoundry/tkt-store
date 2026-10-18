# tkt-store

A ticket store for coordinating AI agents, kept on a git branch.

> **Status: being rebuilt from the bottom up.** The previous implementation is release
> 0.1.0 (tag `v0.1.0`). This rebuild designs tkt-store again, layer by layer; anything
> about tkt-store beyond what is specified below is TBD.

## How it is built

tkt-store is built in layers, each a package of its own under `src/`:

| Layer | What it is | Status | Specified in |
|---|---|---|---|
| **The ticket layer** | tkt-store's tickets and claims, and the interface agents use: its guarantees, commands and usage | TBD | TBD |
| **state-store**, the storage layer | Where tkt-store keeps all of its state: a key/value store on a git branch, with snapshot reads and all-or-nothing commits that land only if nothing changed since the snapshot. It knows nothing about tickets. | Specified; a skeleton (interface and tests), not yet implemented | [`docs/state-store.md`](docs/state-store.md), [`docs/state-store-design.md`](docs/state-store-design.md) |

## Getting started as a developer

You need [uv](https://docs.astral.sh/uv/) and git 2.29 or later; uv fetches the Python
in `.python-version` (3.11, the oldest supported, as CI uses) if you have none. Do not
use `pip`. Once per clone:

```sh
git clone https://github.com/WillCodeFoundry/tkt-store.git
cd tkt-store
uv sync --group dev        # .venv from uv.lock, with the dev tools (they are opt-in)
uv run pre-commit install  # git hooks that run the checks on commit and push
```

From then on the checks run themselves: on `git commit`, ruff, mypy and the tests that
need no git; on `git push`, the whole suite. A failing check stops the commit or push
and says why. To check work without committing:

```sh
uv run pre-commit run                        # what a commit checks
uv run pre-commit run --hook-stage pre-push  # the whole suite
```

The rules for changes (where each change is specified, tooling, checks, tests, commits)
are in [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

## Documentation

| Document | What |
|---|---|
| [`docs/state-store.md`](docs/state-store.md) | state-store: what it promises (interface, guarantees, errors, keys) |
| [`docs/state-store-design.md`](docs/state-store-design.md) | state-store: how it keeps those promises on git |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Where changes are specified, tooling, checks, testing, commit rules |

The ticket layer's documents are TBD.

## Repository layout

| Path | What |
|---|---|
| `docs/` | All documentation |
| `src/state-store/` | The storage layer: the `state_store` package and its tests in `tests/` |
| `src/tkt-store/` | The ticket layer: no code yet (TBD) |
| `pyproject.toml` | The uv workspace: its members (the packages under `src/`), the dev tools and their settings |
