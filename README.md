# tkt-store

A small ticket store for coordinating AI agents. Tickets live as JSON files on a
dedicated git branch; every change is one commit published by compare-and-swap,
so "who holds which ticket" has exactly one answer.

> **Status: skeleton.** Interfaces, data structures and documentation are
> specified; logic is stubbed (`NotImplementedError`). This revision exists for
> architecture review — see `docs/design.md`.

## What it guarantees

- **One live holder per ticket.** A claim is refused while another holder's lease is live.
- **Atomic changes.** Each operation is one commit; a lost race is a clean `Conflict`, never a partial write.
- **Fenced claims.** Renew / release / done must present the claim's `claim_id`; a stale holder is refused.
- **Safe to repeat.** Re-running an operation converges instead of duplicating it.
- **Auditable.** The branch's git history is the event log (commit trailers record op, ticket, agent).

## What it is not

Not a coordinator, not a scheduler, not a code-delivery tool. It does not run
agents, create worktrees, or merge code. A coordinator process uses it via
`tkt_store.open_store(repo)`, which returns a `TicketStore`.

## Quickstart (target behaviour)

```sh
tkt --repo ~/tasks.git init
tkt add "Expire reset tokens" --kind task --priority 2
tkt claim tkt-7f3a --as coder-7 --ttl 30m      # prints a claim id
tkt renew tkt-7f3a --claim c9f2… --ttl 30m
tkt release tkt-7f3a --claim c9f2… --to-stage review   # hand off to the next phase
tkt claim-next --as reviewer-2 --stage review  # a review agent pulls its phase
tkt done  tkt-7f3a --claim d4a1…               # terminal: done
tkt list --stage qa --json
tkt reap                                        # release expired claims
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
| interface / root | `cli`; `open_store()` in `__init__` (composition root) | `application` (+ `infrastructure` at the composition root only) |

## Development

```sh
pip install -e '.[dev]'
pre-commit install
pytest
```
