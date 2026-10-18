# state-store

A key/value store on a git branch. Take a snapshot, derive new snapshots that carry
your changes, and commit one: it lands only if nothing has changed since the snapshot
you started from, otherwise it is rejected and you start again from a new snapshot.

> **Status: skeleton.** This document, the interface and the tests exist; the
> implementation does not yet (only the error types do). Every test of unimplemented
> behaviour is a strict expected failure until the code it covers lands.

It is the component of tkt-store that keeps all of tkt-store's state, and knows nothing
about tickets: keys are strings, values are bytes. How it maps onto git is in
[`design.md`](design.md).

## Why

tkt-store needs shared state that many agents change concurrently, with changes that
span several keys and must land together or not at all, without running a server. A git
branch on a remote that every agent can push to gives durability, an audit trail and,
through compare-and-swap pushes, a single order of changes. This package turns that
into a small key/value interface, so the rest of tkt-store never needs to know git.

## Model

| Term | Meaning |
|---|---|
| **store** | One branch of one remote, read and written through a local clone. |
| **key** | A path-like string, e.g. `tickets/tkt-1234` (grammar below). |
| **value** | Bytes, at most `MAX_VALUE_SIZE` (1 MiB). Never interpreted. |
| **namespace** | A key prefix: `tickets` holds `tickets/tkt-1234`. `""` is the root. |
| **snapshot** | An immutable view of every key at one moment (one commit of the branch), plus any changes derived from it. |
| **commit** | Publishing a snapshot's changes as the store's new state. |

## Example

```python
from state_store import GitStateStore, StaleSnapshot

store = GitStateStore("/work/tasks", remote="origin", branch="tkt-store")

while True:
    snap = store.snapshot()
    if snap.get("tickets/tkt-0") is None:
        break  # nothing to do
    next_snap = snap.without("tickets/tkt-0").with_value("archive/tkt-0", b'{"resolution": "done"}')
    try:
        store.commit(next_snap, "done tkt-0")
        break
    except StaleSnapshot:
        continue  # someone committed first: decide again on the new state
```

A real caller bounds the loop and backs off between attempts; the store never retries
by itself, because only the caller can redo its decision on new data.

## Interface

```python
class StateStore(Protocol):
    def snapshot(self) -> StateSnapshot: ...
    def commit(self, snapshot: StateSnapshot, message: str) -> StateSnapshot: ...

class StateSnapshot:                       # immutable
    revision: str | None                   # the commit it was taken from; None: empty store
    changes: Mapping[str, bytes | None]    # what it changes, relative to `revision`
    def get(self, key: str) -> bytes | None
    def keys(self, namespace: str = "") -> list[str]
    def with_value(self, key: str, value: bytes) -> StateSnapshot
    def without(self, key: str) -> StateSnapshot
```

- `store.snapshot()` takes the store's current state from the remote.
- `snap.get(key)` returns the value, or `None` if there is none (including when `key`
  is a namespace, or a path through a value).
- `snap.keys(namespace)` returns the full keys of the values directly in that namespace,
  sorted. Values in nested namespaces are not included: `keys("tickets")` lists
  `tickets/tkt-1`, not `tickets/old/tkt-2`. A namespace that does not exist, or that is
  a value, lists nothing.
- `snap.with_value(key, value)` and `snap.without(key)` return a **new** snapshot with
  the change; `snap` is unchanged. They chain, and reads from the new snapshot see the
  changes (`next_snap.get(key)` returns the new value before anything is committed).
  `without` removes one value: `without("tickets")` removes nothing if `tickets` is a
  namespace.
- `store.commit(snap, message)` publishes `snap`'s changes as one commit and returns the
  committed state as a new snapshot (no changes, a new `revision`). The message is any
  text without NUL characters, empty included.
- **A snapshot that changes nothing commits nothing.** `commit` returns the snapshot it
  derives from (same `revision`, no changes) without contacting the remote, so this is
  not a freshness check: the store may have moved on. Writing a value a key already
  has, or removing a key that has none, changes nothing.

Implementations:

- `GitStateStore(repo, *, remote="origin", branch)`: the real store, in a clone at
  `repo`.
- `MemoryStateStore()`: the same semantics in memory, for tests of code built on the
  store. One instance stands for one remote that many writers share.

## Guarantees

1. **Consistent reads.** Every read from a snapshot sees the same moment, however long
   after it was taken.
2. **All or nothing.** A commit publishes every change of its snapshot, or none.
3. **Commits apply one at a time, each on the latest state.** A commit lands only if
   the store has not changed since the snapshot it derives from was taken. So the
   committed states form a single line, and every commit was decided on the state just
   before it: in database terms, serializable, in commit order. Two writers that read
   the same keys and write different ones cannot both land. (A snapshot that changes
   nothing commits nothing and checks nothing, see above.)
4. **Durable when `commit` returns.** The remote has accepted the commit. When the
   outcome cannot be known (the connection failed mid-push), `commit` says so
   (`UnknownOutcome`) instead of guessing.
5. **An audit trail.** Every commit is a git commit, with its message and its author
   (git's configured identity); `git log` on the branch shows every change. The store
   itself never reads history: the current state is always read directly.
6. **It fails loudly.** Anything on the branch that the store would never have written
   (a symlink, an executable file, a submodule, a bad or repeated name, an oversized
   value) is a `StoreError`, never skipped. A read fails only if it touches the bad
   entry: `get` checks the entries on its key's path, `keys` checks the whole namespace
   it lists. A commit checks every namespace it rewrites, so it never carries a bad
   entry into a new commit; repairing one takes plain git (see [the design](design.md)).

These hold under two preconditions:

- **The remote refuses non-fast-forward pushes and deletion of the branch** (a ruleset
  on GitHub; `receive.denyNonFastForwards` and `receive.denyDeletes` on a bare
  repository). The store never does either, and compare-and-swap does not depend on
  it, but it stops other writers rewriting history.
- **Every writer goes through this package.** Anyone with push access and plain git can
  write anything well-formed; the store checks what it reads, not who wrote it.

## What it does not do

- **Retry.** A lost race is `StaleSnapshot`; the caller decides again.
- **Detect conflicts per key.** Any two concurrent commits conflict, even on unrelated
  keys, and one of them must start again. Throughput is about one commit per remote
  round trip; that is the price of guarantee 3.
- **Lock, query, index or expire.** There are `get`, `keys`, and an atomic batch write.
- **Touch files.** It never checks out or writes a working tree; values exist only as
  git objects.
- **Clone.** Make the clone with `git clone --no-checkout`.
- **Cache across processes.** Each snapshot reads what it needs, lazily, and remembers
  it for its own lifetime only.

## Errors

| Error | Meaning | The caller |
|---|---|---|
| `StaleSnapshot` | The store changed since the snapshot was taken. Nothing was published. | Takes a new snapshot and decides again. |
| `UnknownOutcome` (a `StaleSnapshot`) | The connection failed during the push: the commit may or may not have landed. | The same; the new snapshot shows whether it landed. A caller whose changes are not safe to repeat must check for them before deciding again. |
| `StoreError` | Anything else; `.category` says what (table below). Never retried by the store. | Stops; an operator acts. |
| `KeyCollision` (a `ValueError`) | A write would make a key both a value and a namespace. It can come from data another writer stored, not only from this caller's code. | Treats it as a schema conflict between writers: stops. |
| `ValueError` | A caller bug: an invalid key, namespace, branch or remote name, a value that is not bytes or is too large, a message with NUL, a snapshot from another store object. | Fixes the code. |

Reads are lazy, so `get`, `keys` and `with_value` (which checks collisions against the
stored state) can raise `StoreError` too, never only `snapshot` and `commit`.

| `StoreError.category` | Meaning |
|---|---|
| `CORRUPT` | The branch holds something the store would never write (guarantee 6). |
| `REFUSED` | The remote refused a commit for a reason other than a lost race (a hook, a protection rule). |
| `AUTH` | The remote refused access. |
| `NOT_FOUND` | The remote's repository does not exist. |
| `UNREACHABLE` | The remote could not be reached. |
| `UNRECOGNISED` | A remote command failed in a way the store does not recognise. |
| `NO_IDENTITY` | git has no `user.name` / `user.email` to author commits with. |
| `NOT_A_CLONE` | The path is not a usable clone: not a repository's top level, shallow, partial, or its remote is not configured as required (see *Requirements*). |
| `LOCAL` | A local git command failed for another reason. |

No error message ever contains text git or the remote printed, or a value read from
the store; git's own text goes to a log in the clone's git directory, for an operator
(see [the design](design.md)).

## Keys

A key is one or more **segments** joined by `/`, at most 1024 characters. A segment
is 1 to 128 characters from `A-Z a-z 0-9 . _ -`, and starts with a letter, digit or
`_` (so never `.`, `..`, `.git`, or something that looks like an option). Keys are
case-sensitive. A namespace argument is `""` or a valid key.

A key cannot be both a value and a namespace: with `tickets/tkt-1` stored,
`with_value("tickets", …)` is a `KeyCollision`, and so is `with_value("tickets/tkt-1/x",
…)`. A namespace exists while it holds at least one value; removing its last value
removes it. Removing every value leaves an empty store whose `revision` is a commit, not
`None`: `revision` is `None` only before the first commit.

**Choose namespaces deliberately.** Each namespace is a git tree, and a commit rewrites
every namespace on the path of every key it changes, in full. Keep large namespaces
that keep growing (an archive) apart from small busy ones (open work), and never put
everything at the root: a commit touching one small key would then rewrite a listing of
everything ever stored.

## Requirements

- git 2.15 or later (why: [the design](design.md), §7).
- A full, non-bare clone, made without a checkout (`git clone --no-checkout`), given as
  its top-level directory. Shallow, partial and bare clones are refused. One store
  (one branch) per clone.
- One process at a time per clone. Two processes using one clone at once can fail with
  `StoreError(LOCAL)`; give each process its own clone.
- `remote` is the name of a remote configured in the clone, not a URL, with exactly
  one URL, used for both fetching and pushing (no `pushurl`, no rewriting that makes
  them differ). Otherwise a push could reach a different server from the one checked.
- `branch` is a plain branch name (`tkt-store`): not `refs/heads/…`, `@` or `HEAD`, and
  not starting with `-`.
- Nobody runs git against the clone or the branch by hand while writers are active.
- Keep credentials out of the remote's URL: the operator log (see [the design](design.md)) may quote
  it, and anything that can read the clone can read the log.

## Testing

Code built on the store tests against `MemoryStateStore`. The store's own tests in
`src/state-store/tests/` run every behaviour in `test_contract.py` against both
implementations, so the two never drift apart; `test_git.py` covers what only the git
store has (the remote, corrupt branches, errors, hooks).
