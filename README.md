# tkt-store

A ticket store for coordinating AI agents, kept on a git branch.

> **Status: being rebuilt.** The previous implementation is release 0.1.0 (tag
> `v0.1.0`). This rebuild designs tkt-store again, starting from how it stores its
> state; anything about tkt-store beyond what is specified below is TBD.

## Overview

| Part | What it is | Status |
|---|---|---|
| **tkt-store** | Tickets and claims for coordinating agents, and the interface agents use | TBD; the decisions made so far are in [`docs/tkt-store/decisions/`](docs/tkt-store/decisions/README.md) |
| **state-store**, a component of tkt-store | Where tkt-store keeps all of its state: a key/value store on a git branch, with snapshot reads and all-or-nothing commits that land only if nothing changed since the snapshot. It knows nothing about tickets. | Specified; a skeleton (interface and tests), not yet implemented |

## Prerequisites

- [git](https://git-scm.com/) 2.15 or later.
- [uv](https://docs.astral.sh/uv/), which manages the environment, the dependencies and
  the tools. It fetches the Python version in `.python-version` (3.11) if you have none.
  Do not use `pip`.

## Getting started

Once per clone:

```sh
git clone https://github.com/WillCodeFoundry/tkt-store.git
cd tkt-store
uv sync --group dev        # the environment, from uv.lock, with the dev tools
uv run pre-commit install  # git hooks that run the checks on commit and push
```

From then on, committing and pushing run the checks. How the checks work, how to test,
and the rules for commits are in [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

## Usage

How agents use tkt-store is TBD. The interface of state-store is in
[`docs/state-store/README.md`](docs/state-store/README.md).

## Documentation

All documentation is in [`docs/`](docs/README.md), which maps it: tkt-store and
state-store each have a directory with what they promise, how they keep those promises,
and the decisions behind them.

## Contributing

Read [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) before changing anything: it says
which document specifies each kind of change, and the rules every change follows.

## Project layout

| Path | What |
|---|---|
| `docs/` | All documentation: `CONTRIBUTING.md`, and a directory each for tkt-store and state-store |
| `src/tkt-store/` | tkt-store: no code yet (TBD) |
| `src/state-store/` | state-store: the `state_store` package and its tests in `tests/` |
| `pyproject.toml` | The uv workspace: its members (the packages under `src/`), the dev tools and their settings |
