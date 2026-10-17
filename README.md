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

Keep the store in its own repository; `tkt` uses only the `tkt-store` branch. Requires
git 2.29 or later.

**One clone per process.** Give every process that runs `tkt` its own clone of the store
repository, and never let two processes use the same clone, for example by mounting one
clone into several containers. Each clone keeps a cache of what it has already read in
`.git/tkt-store/cache/`; deleting it is always safe (the next command reads the store in
full once). When a git command fails, tkt's error says only what kind of failure it
was; git's own message is in `.git/tkt-store/git-errors.log`. It may quote
the server, and the remote's URL as git printed it, credentials included if the URL
holds them, so read it yourself rather than passing it to an agent. Partial clones
(`git clone --filter`) are refused: make a full clone.

**Agents use only `tkt`, never git, on the store.** `tkt` validates what it writes (and,
from 0.2.0, everything it reads), never checks out files (so no checkout hooks, filters
or symlinks are ever involved), and writes only by compare-and-swap; from 0.2.0 it also
refuses to act as another agent's holder. Plain git does none of that: an agent running
it can forge tickets and history that other agents then trust. Make each clone without a
checkout (`git clone --no-checkout`; from 0.2.0, `tkt clone`), and give agents only the
`tkt` command for the store. The security model behind this is in `docs/design.md` §8
and ADR 0005.

**One git identity per agent.** From 0.2.0, `tkt` records who did each operation as the
commit author, the identity git itself uses (`user.name` and `user.email`), and refuses
to write without one. Give each agent its own, for example a name such as `coder-7` and
a GitHub noreply address: the store's history is readable by everyone with access to the
repository, and GitHub can refuse pushes that would expose a private address.

The remote's repository is shared by all clones, so it needs the same care. A remote
given as a file path (a bare repository) is only safe when every clone is on the same
machine as that repository, with the same filesystem. If clones live in VMs or sandboxes
(Docker Desktop, Docker Sandboxes) or on other machines, don't mount the remote's
directory into them: git's locking may not hold across that boundary, and two agents
could both get the same claim. A path remote is also a security risk: every agent can
write the repository's files, so a compromised agent can plant a hook or change its
config, and that hook then runs inside every other agent that pushes. Use a path remote
only for agents that fully trust each other; otherwise serve it over the network (a
hosting service, SSH, or `git daemon`), so that only its own machine writes to it.

**Any git server works as the remote:** a hosting service such as GitHub, a bare
repository over SSH or `git daemon`, or, when every clone is on the same machine as the
repository, a bare repository's path. Every `tkt` write is one fetch and one push. The
server must:

- **accept direct pushes to `tkt-store`:** no pull-request, status-check or
  signed-commit requirement on that branch (store commits are unsigned);
- **refuse force pushes and deletion of `tkt-store`,** however your server does that,
  e.g. a ruleset on GitHub, or `receive.denyNonFastForwards` and `receive.denyDeletes`
  on a plain bare repository. `tkt` itself never does either; this protects the history
  from other writers.

`git daemon` is for trusted local agents only (e.g. agents in containers or VMs on one
host). It runs no code from the agents, but it has no authentication: anything that can
reach its port can push anything with plain git, forged tickets included. Bind it to
loopback, and use SSH if you need authentication:

```sh
git daemon --reuseaddr --base-path=/srv/git --export-all \
  --enable=receive-pack --listen=127.0.0.1 --port=9418
```

Agents then clone `git://<host>/tkt.git`; from a Docker Sandbox the host is
`host.docker.internal`, once the port is allowed (`sbx policy allow network
localhost:9418`).

**Check the protection** once the store exists (`tkt init`). The script tries a
non-fast-forward push and a deletion of the store branch, reports whether each was
refused, and restores the branch if either was accepted:

```sh
uv run python scripts/check_remote.py --repo /work/tasks --remote origin
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
| `scripts/` | `check_remote.py`: checks a store's remote is protected; `bench.py`: the ADR 0001 benchmark (dedicated test repositories only) |

The package is organised in layers, with dependencies pointing inward only
(enforced by `tests/unit/test_architecture.py`):

| Layer | Modules | Depends on |
|---|---|---|
| `domain/` | `ticket`, `status`, `operations`, `outcomes`, `rules`, `errors` | nothing but itself |
| `application/` | `store`, `clock`, `ids` (ports), `transaction`, `service`, `history`, `errors` | `domain` |
| `infrastructure/` | `git/{runner,wire,remote,repo}`, `memory`, `clock`, `ids` | `domain`, `application` |
| interface | `cli` | `application` (and `domain` types) + the composition root (`__init__`: `open_store`, `new_id_source`); never `infrastructure` |
| root | `open_store()` in `__init__` (composition root) | every layer |

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environments,
dependencies and running tools. Do not use `pip`.

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

**Before committing**, run the checks CI runs; they must pass:

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
```

**The git hooks** are a safety net, not the check. On `git commit` they run ruff, mypy
and the tests that need no git (about 8 s); on `git push`, the whole suite (about a
minute), as CI's test job runs it. Every tool's version is pinned once, in the `dev`
group of `pyproject.toml`; the hooks run it with `uv run`.

`uv.lock` is tracked; commit it whenever dependencies change. See `AGENTS.md` for the
commit rules and the Claude Code hook.
