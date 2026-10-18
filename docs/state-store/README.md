# state-store

A key/value store on a git branch. Take a snapshot, derive new snapshots that carry
your changes, and commit one: it lands only if nothing has changed since the snapshot
you started from, otherwise it is rejected and you start again from a new snapshot.

> **Status: skeleton.** This document, the interface and the tests exist; the
> implementation does not yet (only the error types do).

It is general-purpose: keys are strings, values are bytes, and it interprets neither.
This document is the specification: what state-store promises. How the stores keep
those promises is in [`design.md`](design.md), and why it is built this way is in
[`decisions/`](decisions/README.md), starting with
[what it provides](decisions/0001-provide-consistent-all-or-nothing-shared-state.md).

## Model

| Term | Meaning |
|---|---|
| **store** | The shared state: a set of keys, each holding a value, that many writers read and change. |
| **store object** | What one caller uses to read and change a store (see *Store objects*). |
| **key** | A path-like string, e.g. `inbox/item-1` (grammar below). |
| **value** | Bytes, at most `MAX_VALUE_SIZE` (1 MiB). Never interpreted. |
| **namespace** | A key prefix: `inbox` holds `inbox/item-1`. `""` is the root. |
| **revision** | The id of one committed state of the store. A new store is at a first revision, empty. |
| **snapshot** | An immutable view of the store at one revision. A *taken* snapshot comes from the store object; a *derived* snapshot is a taken one plus changes. |
| **change** | Setting a key to a value, or removing it, in a derived snapshot. |
| **commit** | Publishing a derived snapshot's changes as the store's next revision, only if the store is still at the revision the snapshot was taken at: a **compare-and-swap**. |

## Example

```python
from state_store import CompareAndSwapFailed, GitStateStore, UnknownOutcome

store = GitStateStore("/work/store")  # a clone made once by GitStateStore.clone

while True:
    snap = store.snapshot()
    if snap.get("inbox/item-0") is None:
        break  # nothing to do
    next_snap = snap.without("inbox/item-0").with_value("archive/item-0", b"processed")
    try:
        store.commit(next_snap, "archive item-0")
        break
    except (CompareAndSwapFailed, UnknownOutcome):
        continue  # decide again on the new state, which shows whether an unknown commit landed
```

A real caller bounds the loop and backs off between attempts.

## Interface

```python
class StateStore(Protocol):
    def snapshot(self) -> StateSnapshot: ...
    def commit(self, snapshot: StateSnapshot, message: str) -> StateSnapshot: ...

class StateSnapshot:                       # immutable
    revision: str                          # the revision it was taken at
    changes: Mapping[str, bytes | None]    # its changes, as given; None for a removal
    def get(self, key: str) -> bytes | None
    def keys(self, namespace: str = "") -> list[str]
    def with_value(self, key: str, value: bytes) -> StateSnapshot
    def without(self, key: str) -> StateSnapshot
```

- `store.snapshot()` takes a snapshot of the store's latest revision.
- `snap.get(key)` returns the value, or `None` if there is none (including when `key`
  is a namespace, or a path through a value).
- `snap.keys(namespace)` returns the full keys of the values directly in that namespace,
  sorted. Values in nested namespaces are not included: `keys("inbox")` lists
  `inbox/item-1`, not `inbox/old/item-2`. A namespace that does not exist, or that is
  a value, lists nothing.
- `snap.with_value(key, value)` and `snap.without(key)` return a **new** snapshot with
  the change; `snap` is unchanged. They chain, and reads from the new snapshot see the
  changes (`next_snap.get(key)` returns the new value before anything is committed).
  `without` removes one value: `without("inbox")` removes nothing if `inbox` is a
  namespace.
- `store.commit(snap, message)` publishes `snap`'s changes as one commit and returns a
  snapshot of the new revision, without changes. The message is any text without NUL
  characters, empty included.
- **A snapshot that changes nothing commits nothing.** `commit` returns the taken
  snapshot it derives from, without contacting the remote, so this is not a freshness
  check: the store may have moved on. Writing a value a key already has, or removing a
  key that has none, changes nothing.

## Store objects

- `GitStateStore.clone(path, *, url, branch)`: clones `branch` of the remote at `url`
  to `path`, which must not exist, and returns the store on it. Run once per clone;
  the branch must already exist on the remote.
- `GitStateStore(path)`: the store through the clone at `path`, which `clone` made.
  Opening never contacts the remote. Its requirements are under *Git store*.
- `MemoryStateStore()`: the same semantics in memory, for testing code that uses
  state-store. One instance stands for one store that many writers share, starting
  empty. It never raises `StoreError` or `UnknownOutcome` by itself.

## Guarantees

The errors named here are described under [Errors](#errors).

1. **Consistent reads.** Every read from a snapshot sees the same revision, however long
   after the snapshot was taken.
2. **All or nothing.** A commit publishes every change of its snapshot, or none.
3. **Commits apply one at a time, each on the latest revision.** Every commit is a
   compare-and-swap, so the revisions form a single line, and every commit was decided
   on the revision just before it: two writers that read the same keys and write
   different ones cannot both land.
4. **Durable when `commit` returns.** When the outcome cannot be known (for example, the
   connection failed during the commit), `commit` says so (`UnknownOutcome`) instead of
   guessing.
5. **It fails loudly.** An operation that depends on something the store would never
   have written fails with `CorruptState` instead of skipping it;
   operations that do not depend on it are unaffected, and a commit that changes a key
   in a namespace holding it fails too. Repairing it is described in
   [the design](design.md#4-corrupt-entries-in-git).

For the git store these hold under the preconditions in *Git store*.

## What it does not do

- **Retry.** A lost race is `CompareAndSwapFailed`; the caller decides again.
- **Detect conflicts per key.** Any two concurrent commits conflict, even on unrelated
  keys, and one of them must start again (what that costs:
  [decision 0001](decisions/0001-provide-consistent-all-or-nothing-shared-state.md)).
- **Lock, query, index or expire.** There are `get`, `keys`, and an atomic batch write.
- **Keep values secret** ([why](decisions/0003-trust-only-the-callers-machine-and-the-remotes-handling-of-pushes.md)).

## Errors

| Error | Meaning | The caller |
|---|---|---|
| `CompareAndSwapFailed` | The branch the commit was pushed to was not at the snapshot's revision: another writer committed first. Nothing was published. | Takes a new snapshot and decides again. |
| `UnknownOutcome` | The commit's outcome could not be read (for example, the connection failed during the commit): it may or may not have landed. | Takes a new snapshot and decides again; the new snapshot shows whether it landed. A caller whose changes are not safe to repeat must check for them before deciding again. |
| `StoreError` | Anything else; its kinds are below. | Stops; an operator acts. |
| `KeyCollision` (a `ValueError`) | A write would make a key both a value and a namespace. It can come from data another writer stored, not only from this caller's code. | Treats it as a conflict between writers: stops. |
| `ValueError` | A caller bug: an invalid key, namespace or branch name, an empty URL, a value that is not bytes or is too large, a message with NUL, a snapshot from another store object. | Fixes the code. |

The kinds of `StoreError` (each a subclass), raised by the git store only:

| Error | Meaning |
|---|---|
| `CorruptState` | The branch holds something the store would never write (guarantee 5). |
| `CommitRefused` | The remote refused the commit, and the branch did not move (a hook, a protection rule). |
| `UnusableRepository` | `path` is not a clone the store made, or it was changed by hand since, or the user's git configuration changes its remote; or, when cloning, `path` already exists or the clone could not be put there. |
| `NoSuchBranch` | The branch does not exist on the remote: when cloning, or when taking a snapshot. |
| `PushElsewhere` | A snapshot found that this store object's last commit does not match the branch (a published commit missing from its history, or a failed compare-and-swap while the branch had not moved): pushes reach a different repository from fetches. |
| `NoIdentity` | git has no author identity to commit with. |
| `GitFailed` | A git command failed. |
| `RemoteFailed` (a `GitFailed`) | Cloning, fetching, or checking whether the branch exists, failed. |

Every operation but `without` can raise `StoreError`: when git fails, or, for `get`,
`keys`, `with_value` (which checks collisions against the stored state) and `commit`,
when what it reads is corrupt.

An error's message holds only state-store's own text: the operation, the git command,
and the check that failed. It never holds a key (the caller knows which key it passed), a
value, or text from outside state-store, such as git's output.

## Keys

A key is one or more **segments** joined by `/`, at most 1024 characters. A segment
is 1 to 128 characters from `A-Z a-z 0-9 . _ -`, and starts with a letter, digit or
`_` (so never `.`, `..`, `.git`, or something that looks like an option). Keys are
case-sensitive. A namespace argument is `""` or a valid key.

A key cannot be both a value and a namespace: with `inbox/item-1` stored,
`with_value("inbox", …)` is a `KeyCollision`, and so is `with_value("inbox/item-1/x",
…)`. A namespace exists while it holds at least one value; removing its last value
removes it. Removing every value leaves an empty store, at a new revision.

**Choose namespaces deliberately.** A commit costs time in proportion to the size of
every namespace on the path of each key it changes (why:
[the design](design.md#5-committing)). Keep large namespaces that keep growing (an
archive) apart from small busy ones, and do not put everything at the root.

## Git store

What applies to `GitStateStore` only.

**Preconditions** for the guarantees:

- **The remote applies pushes and reports their outcome truthfully, and fetching,
  `ls-remote` and pushing all see the same state of it** (not replicas that lag
  behind)
  ([0003](decisions/0003-trust-only-the-callers-machine-and-the-remotes-handling-of-pushes.md)).
  Guarantees 2 to 4 depend on it: nothing can detect a remote that does not.
- **The remote refuses force pushes and deletion of the branch** (a ruleset on GitHub;
  `receive.denyNonFastForwards` and `receive.denyDeletes` on a bare repository).
  Guarantee 1 depends on it for old snapshots, which stay readable only while history
  is never rewritten (why: [the design](design.md#3-taking-a-snapshot-and-reading)).
  The store never does either, and compare-and-swap does not depend on it
  ([the design](design.md#5-committing)).
- **Every writer goes through state-store.** Guarantee 3 depends on it: a commit made
  with plain git can land without having been decided on the revision before it, and
  nothing can tell.

**Requirements:**

- git 2.14 or later (why: [the design](design.md#6-running-git)).
- The branch exists on the remote before the first clone. To create it, push one
  commit of the empty tree, from any repository with the remote's object format (any
  new one, for the usual SHA-1):
  ```
  tree=$(git hash-object -t tree /dev/null)
  git push <url> "$(git commit-tree -m 'Create the store' "$tree")":refs/heads/<branch>
  ```
- `path` is a clone that `GitStateStore.clone` made; the store refuses anything else
  ([the design](design.md#7-cloning-and-opening)). One process at a time per clone.
- `url` is the remote's URL, used for both fetching and pushing. The user's git
  configuration may rewrite it (`insteadOf`, `pushInsteadOf`), or give the remote
  named `origin` one push URL (`pushurl`), but fetches and pushes must reach the same
  repository; a store that finds otherwise at its next snapshot raises
  `PushElsewhere`. The configuration must not configure `origin` otherwise. A local
  path given as `url` is absolute: git would resolve a relative one from the caller's
  working directory.
- `branch` is a plain branch name (`state`) that git accepts as `refs/heads/<branch>`:
  it does not start with `refs/` or `-`, and is not `@` or `HEAD`.
- Nobody runs git in the clone by hand while writers are active.
- Credentials are kept out of the URL (use a credential helper): the operator log
  (below) can quote the URL, and anything that can read the clone can read it.

Each commit is a git commit with the caller's message and the writer's git identity as
its author, from the user's git configuration or environment.

git's own output, which errors never carry, goes to a log in the clone's git directory,
for an operator ([the design](design.md#8-errors-and-the-operator-log)).
