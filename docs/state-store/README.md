# state-store

A key/value store on a git branch. Take a snapshot, derive new snapshots that carry
your changes, and commit one: it lands only if nothing has changed since the snapshot
you started from, otherwise it is rejected and you start again from a new snapshot.

> **Status: skeleton.** This document and the interface exist; the implementation does
> not yet.

It is general-purpose: keys are strings, values are bytes, and it interprets neither.
This document is the specification. How the git store works is in
[`design.md`](design.md), and why it is built this way is in
[`decisions/`](decisions/README.md).

## Model

| Term | Meaning |
|---|---|
| **store** | A set of keys, each holding a value, that many writers read and change. |
| **key** | A path-like string, e.g. `inbox/item-1` (grammar below). |
| **value** | Bytes, at most `MAX_VALUE_SIZE` (1 MiB). Never interpreted. |
| **namespace** | A key prefix: `inbox` holds `inbox/item-1`. `""` is the root. |
| **revision** | The id of one committed state. A new store is at a first revision, empty. |
| **snapshot** | An immutable view of the store at one revision, plus any changes derived from it. |
| **commit** | Publishing a snapshot's changes as the next revision, only if the store is still at the snapshot's revision: a **compare-and-swap**. |

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
    revision: str
    changes: Mapping[str, bytes | None]    # None for a removal
    def get(self, key: str) -> bytes | None
    def keys(self, namespace: str = "") -> list[str]
    def with_value(self, key: str, value: bytes) -> StateSnapshot
    def without(self, key: str) -> StateSnapshot
```

- `get(key)` returns the value, or `None` if there is none.
- `keys(namespace)` returns the full keys of the values directly in `namespace`, sorted;
  not those in nested namespaces.
- `with_value` and `without` return a new snapshot with the change; reads from it see
  the change. The original is unchanged.
- `commit(snap, message)` publishes `snap`'s changes as one commit and returns a
  snapshot of the new revision. A snapshot that changes nothing commits nothing.

Store objects:

- `GitStateStore.clone(path, *, url, branch)`: clones `branch` of the remote at `url`
  to `path`, once, and returns the store on it. The branch must already exist.
- `GitStateStore(path)`: the store through the clone at `path` that `clone` made.
  Opening never contacts the remote.
- `MemoryStateStore()`: the same semantics in memory, for tests of code that uses
  state-store. It starts empty, at a first revision.

## Guarantees

1. **Consistent reads.** Every read from a snapshot sees the same revision.
2. **All or nothing.** A commit publishes every change of its snapshot, or none.
3. **One commit at a time, each on the latest revision.** Two writers that read the
   same state cannot both commit on it.
4. **Durable when `commit` returns.** When the outcome cannot be known, `commit` says so
   instead of guessing.
5. **Corrupt state fails loudly.** Reading something the store would never have written
   is an error, never skipped.

The store does not retry, detect conflicts per key, lock, query, or keep values secret.

## Errors

| Error | Meaning | The caller |
|---|---|---|
| `CompareAndSwapFailed` | The branch was not at the snapshot's revision: another writer committed first. Nothing was published. | Takes a new snapshot and decides again. |
| `UnknownOutcome` | The commit's outcome could not be read: it may have landed. | Takes a new snapshot and decides again; it shows whether the commit landed. |
| `StoreError` | Anything else: corrupt state, the remote refused the commit, git failed, no such branch. The message says which. | Stops; an operator acts. |
| `ValueError` | An invalid key, value, branch name or message, or a write that would make a key both a value and a namespace. | Fixes the code, or stops. |

Error messages never hold a value.

## Keys

A key is one or more segments joined by `/`, at most 1024 characters. A segment is 1
to 128 characters from `A-Z a-z 0-9 . _ -`, starting with a letter, digit or `_`. A key
cannot be both a value and a namespace. A namespace exists while it holds a value.

## Git store

Preconditions for the guarantees:

- The remote applies pushes and reports their outcome truthfully.
- The remote refuses force pushes and deletion of the branch.
- Every writer goes through state-store.

Requirements:

- The branch exists on the remote before the first clone (one commit of the empty tree
  will do).
- A clone is used by one process at a time, and nobody runs git in it by hand while
  writers are active.
- Credentials come from git's configuration, never from the URL.
