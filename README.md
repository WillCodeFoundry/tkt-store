# tkt-store

A small ticket store for coordinating AI agents. Tickets live as JSON files on a
dedicated git branch; every change is one commit published by compare-and-swap,
so "who holds which ticket" has exactly one answer.

> **Status: skeleton.** Interfaces, data structures and documentation are
> specified; logic is stubbed (`NotImplementedError`). This revision exists for
> architecture review — see `docs/design.md`.

## What it guarantees

- **At most one recorded claim per ticket; stale holders are fenced.** Renew / release /
  done must present the claim's `claim_id` (fencing survives completion). Leases are
  advisory: skewed clocks can make two agents briefly believe they hold a ticket, but
  only the recorded claim can change it.
- **Atomic changes.** Each operation is one commit; a lost race is retried on fresh state, never a partial write.
- **Safe to repeat.** Re-running an operation with the same ids (`--id`, `--claim-id`) converges instead of duplicating it.
- **Auditable.** The branch's git history is the event log (commit trailers record op, ticket, agent, time).

These guarantees hold for writers that go through `tkt`, against a remote that refuses
non-fast-forward pushes and branch deletion (see `docs/design.md` §7).

## What it is not

Not a coordinator, not a scheduler, not a code-delivery tool. It does not run
agents, create worktrees, or merge code. Agents use it directly — the `tkt` command,
or `tkt_store.open_store(repo)`, which returns a `TicketStore` — each in its own clone
of the store repository.

## Quickstart (target behaviour)

Each agent runs these against its own clone of the store repository:

```sh
export TKT_REPO=~/work/tasks   # this agent's clone; origin is the shared remote
tkt init                       # once per store; fails if origin is not configured
tkt add "Expire reset tokens" --kind task --priority 2
tkt claim tkt-7f3a --as coder-7 --ttl 30m      # prints a claim id
tkt renew tkt-7f3a --claim c9f2… --ttl 30m
tkt release tkt-7f3a --claim c9f2… --to-stage review   # hand off to the next phase
tkt claim-next --as reviewer-2 --stage review  # a review agent pulls its phase
tkt done  tkt-7f3a --claim d4a1…               # terminal: done
tkt list --stage qa --json
tkt reap                                        # release lapsed claims (any writer, on a schedule)
```

## Layout

| Path | Purpose |
|---|---|
| `docs/design.md` | Concepts, module boundaries, invariants, failure model |
| `docs/format.md` | On-branch layout, ticket schema, commit trailers |
| `docs/cli.md` | Commands, exit codes, JSON output |
| `docs/decisions/` | Architecture decision records |
| `src/tkt_store/` | The package (layered; see below) |
| `tests/` | Unit, contract, integration and property tests |

The package is organised in layers, with dependencies pointing inward only
(enforced by `tests/unit/test_architecture.py`):

| Layer | Modules | Depends on |
|---|---|---|
| `domain/` | `ticket`, `status`, `operations`, `outcomes`, `rules`, `errors` | nothing but itself |
| `application/` | `store`, `clock`, `ids` (ports), `transaction`, `service`, `history`, `errors` | `domain` |
| `infrastructure/` | `git/{runner,wire,remote,repo}`, `memory`, `clock`, `ids` | `domain`, `application` |
| interface | `cli` | `application` (and `domain` types) + the `open_store` composition root (`__init__`); never `infrastructure` |
| root | `open_store()` in `__init__` (composition root) | every layer |

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environments,
dependencies and running tools. Do not use `pip`.

```sh
uv sync                       # create .venv from uv.lock, with the dev dependency group
uv run pre-commit install     # git hooks as a safety net
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

`uv.lock` is tracked; commit it whenever dependencies change. See `AGENTS.md` for the
commit rules and hooks.
