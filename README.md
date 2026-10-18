# tkt-store

A ticket store for coordinating AI agents, kept on a git branch.

> **Status:** everything about tkt-store beyond its component state-store is TBD.

## Overview

| Part | What it is |
|---|---|
| **tkt-store** | TBD |
| **state-store**, a component of tkt-store | A key/value store on a git branch ([details and status](docs/state-store/README.md)) |

## Prerequisites

- [git](https://git-scm.com/) 2.32 or later, for the tests (state-store's own minimum is
  in [its requirements](docs/state-store/README.md#git-store)).
- [uv](https://docs.astral.sh/uv/), which manages the environment, the dependencies, the
  tools and the Python version ([how](docs/CONTRIBUTING.md#tooling)).

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

How to use tkt-store is TBD. The interface of state-store is in
[`docs/state-store/README.md`](docs/state-store/README.md).

## Documentation

All documentation is in [`docs/`](docs/README.md), which maps it.

## Contributing

Read [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) before changing anything: it says
which document specifies each kind of change, and the rules every change follows.

## Project layout

| Path | What |
|---|---|
| `docs/` | All documentation ([map](docs/README.md)) |
| `src/tkt-store/` | tkt-store: no code yet (TBD) |
| `src/state-store/` | state-store: the `state_store` package and its tests in `tests/` |
| `pyproject.toml` | The uv workspace ([how it is organised](docs/CONTRIBUTING.md#tooling)) |
