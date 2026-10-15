# tkt-store

A small ticket store for coordinating AI agents. Tickets live as JSON files on a
dedicated git branch; every change is one commit published by compare-and-swap,
so "who holds which ticket" has exactly one answer.

> **Status: milestone 1 in progress.** The domain, the git store and the `tkt` CLI
> work end to end (the quickstart below runs as a test). Not yet measured against a
> real GitHub remote; see `docs/decisions/0001-git-branch-as-store.md`.

## What it guarantees

- **At most one recorded claim per ticket; stale holders are fenced.** Renew / move /
  release / done must present the claim's `claim_id` (fencing survives completion). Leases are
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

## Quickstart

The CLI is explicit by design (built for agents): store options on every store command, every
id supplied by the caller (generated with `tkt mint`), TTLs in seconds, JSON out. Each
agent runs it against its own clone of the store repository; a shell variable keeps the
store options short:

```sh
S="--repo /work/tasks --remote origin"

tkt init $S                                                # once per store
TICKET=$(tkt mint ticket-id)
tkt add --id "$TICKET" --title "Expire reset tokens" --kind task --phase implementation $S

CLAIM=$(tkt mint claim-id)                                 # keep it: it identifies this claim
tkt claim "$TICKET" --as coder-7 --ttl 1800 --claim-id "$CLAIM" $S
tkt renew "$TICKET" --claim-id "$CLAIM" --ttl 1800 $S      # every ~10 min while working
tkt move "$TICKET" --claim-id "$CLAIM" --to-phase review $S
tkt release "$TICKET" --claim-id "$CLAIM" $S               # handoff: move, then release

REVIEW=$(tkt mint claim-id)
tkt claim-next --as reviewer-2 --ttl 1800 --phase review --claim-id "$REVIEW" $S
tkt done "$TICKET" --claim-id "$REVIEW" $S
tkt list --phase review $S
tkt reap $S                                                # any writer, on a schedule
```

Store commands print one JSON value: committed and unchanged outcomes list the affected
tickets, and failures print the op with its ids. Re-running any command unchanged is
safe. See `docs/cli.md`.

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
uv sync --group dev           # create .venv from uv.lock, with the opt-in dev tools
uv run pre-commit install     # git hooks as a safety net
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

`uv.lock` is tracked; commit it whenever dependencies change. See `AGENTS.md` for the
commit rules and hooks.
