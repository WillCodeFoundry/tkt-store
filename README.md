# tkt-store

A small ticket store for coordinating AI agents. Tickets live as JSON files on a
dedicated git branch; every change is one commit published by compare-and-swap,
so "who holds which ticket" has exactly one answer.

> **Status: milestone 1.** The domain, the git store and the `tkt` CLI work end to end
> (the quickstart below runs as a test), measured against a protected GitHub branch
> (`docs/decisions/0001-git-branch-as-store.md`).

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
tkt renew "$TICKET" --claim-id "$CLAIM" --ttl 1800 $S      # every ~20 min while working
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

## Deploying

Keep the store in its own repository (`tkt` uses only its `tkt-store` branch), give
every agent process its own full clone and its own git identity, let agents use only
`tkt` (never plain git) on the store, and use a remote that refuses force pushes and
deletion of the branch. Requires git 2.29 or later. The details, and why each matters:
[`docs/deploying.md`](docs/deploying.md).

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
need no git (about 8 s); on `git push`, the whole suite (about a minute). A failing
check stops the commit or push and says why. To check work without committing:

```sh
uv run pre-commit run                        # what a commit checks
uv run pre-commit run --hook-stage pre-push  # the whole suite
```

The rules for changes (tooling, checks, tests, commits) are in
[`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

## Documentation

| Document | What |
|---|---|
| [`docs/design.md`](docs/design.md) | Concepts, module boundaries, invariants, failure model: the authority |
| [`docs/format.md`](docs/format.md) | On-branch layout, ticket schema, commit trailers |
| [`docs/cli.md`](docs/cli.md) | Commands, exit codes, JSON output |
| [`docs/deploying.md`](docs/deploying.md) | Running a store: clones, identities, the remote |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Tooling, checks, testing, commit rules |
| [`docs/decisions/`](docs/decisions/) | Architecture decision records |

The code is in `src/tkt_store/` (layered: [`docs/design.md`](docs/design.md) §3), its
tests in `tests/` (unit, contract, integration, property and security), and `scripts/`
holds `check_remote.py` (checks a store's remote is protected) and `bench.py` (the ADR
0001 benchmark, for dedicated test repositories only).
