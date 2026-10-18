# state-store: design

How the stores keep the promises the [README](README.md) makes. Section 1 applies to
both stores; the rest is about the git store.

## 1. Snapshots and changes

Each store supplies a read-only view of one committed state: it lists a namespace's
entries (each one's name, whether it is a value or a namespace, and a value's size) and
reads a value. Everything else is common to both stores, in one implementation: the
checks on what is read (§4), the merging of changes, and remembering what was read.
So both stores have the same semantics, and only the git store knows git.

**A taken snapshot** is a committed state and its revision. Each namespace is listed,
and each value read, at most once per taken snapshot; every snapshot derived from it
shares what was read.

**A derived snapshot** is the taken snapshot plus its changes: a mapping from key to new
value, or to *removed*. `with_value` and `without` copy that mapping with one more
change; nothing is written anywhere. Reads look in the changes first and fall back to
the committed state. `keys(ns)` merges the committed values directly in `ns` with the
changes: added keys appear, removed ones disappear, nested keys do not count.

**Collisions** are checked when a change is made, against the merged view:
`with_value(k)` raises `KeyCollision` if any proper prefix of `k` is a value, or if `k`
is a namespace that still holds a value. This reads the committed state, so it can
raise `StoreError`. `without(k)` reads nothing and never fails on a valid key.

**A commit** first checks its arguments, then works out whether the snapshot changes
anything (a change can set a value a key already has); only then does it publish, by
compare-and-swap on the revision the snapshot was taken at. `changes` is the mapping as
given, so it can hold changes that change nothing.

**`MemoryStateStore`** keeps its committed states as a list of mappings from key to
value, each with an opaque revision. Its listings are built from the mapping, so they
are always valid. Its commit follows the same steps as the git store's, in the same
order: emptying the store makes a new revision, not `None`. It never raises
`StoreError` or `UnknownOutcome` by itself. The same contract tests run against both
stores.

## 2. Layout on the branch

| Store | Git |
|---|---|
| value | a blob, entry mode `100644` |
| namespace | a tree, entry mode `040000` |
| key `a/b/c` | the path `a/b/c` in the commit's tree |
| committed state | the tree of the branch's tip commit |
| revision | the tip commit's id |
| store never committed to | the branch does not exist |
| store emptied | a commit whose tree is the empty tree |

Nothing else is written, and nothing else is accepted on reading (§4). Git does not
store empty trees, which is why a namespace disappears with its last value.

## 3. Taking a snapshot and reading

```
git fetch --no-tags -- <remote> +refs/heads/<branch>:refs/state-store/<remote>/<branch>
git rev-parse --verify --quiet refs/state-store/<remote>/<branch>^{commit}
```

The branch is fetched into a **private ref** that only state-store writes. There is no
local branch: the remote is the truth, and the private ref is only where the last fetch
landed. The forced refspec (`+`) is safe because nothing else writes the private ref.
Private refs follow git's ref naming, so one clone cannot hold refs for both a branch
`x` and a branch `x/y`, which is one reason for one store per clone.

If the fetch fails, one `git ls-remote -- <remote> refs/heads/<branch>` decides, its
output compared with the exact ref name (`ls-remote` matches patterns on the end of a
name, so `refs/heads/x` also matches `refs/foo/refs/heads/x`):

- the remote lists no such branch: the snapshot is of a store never committed to;
- it lists the branch (created since the fetch looked): fetch once more; a second
  failure is a `StoreError` with the fetch's category;
- `ls-remote` fails too: a `StoreError` with its category.

The snapshot holds the commit id, and all of its reads go to that commit, whose objects
never change: that is guarantee 1. Taking a snapshot transfers objects but reads none.

Reading walks trees by id from the root, never addressing `<commit>:<path>` (which fails
for a missing path, and would mean telling that failure apart from others):

| Step | Git |
|---|---|
| the root tree | `git rev-parse <commit>^{tree}` |
| list a namespace | `git ls-tree -l -z <tree id>` |
| read a value | `git cat-file blob <blob id>` |

`get("a/b/c")` lists the root, `a` and `a/b`, checks the entries on that path (§4), and
finds `c`. A missing segment, or a segment that is a value where a namespace is needed,
means there is no value: `None`. A value's size is checked from the listing before the
blob is read. `keys("a/b")` walks to `a/b` the same way (nothing there: `[]`), lists
it, and checks every entry in it.

**Old snapshots stay readable** while git keeps their objects. Once the private ref has
moved on, an older commit's objects are unreachable, and git only prunes those older
than `gc.pruneExpire` (two weeks by default). Snapshots are meant to live for one
decision, seconds, not weeks.

## 4. Checks on what is read

An entry in a listed tree is valid when:

- its name is a valid key segment ([README](README.md#keys));
- it is a value (`100644 blob`) or a namespace (`040000 tree`);
- a blob's size, from the listing, is at most `MAX_VALUE_SIZE`;
- no other entry in the same tree has the same name (`git mktree` accepts duplicates,
  so a forged tree can hold them).

Anything else (`100755`, `120000` symlinks, `160000` submodules, other names, repeated
names, oversized blobs) is `StoreError(CORRUPT)` for any operation that touches it:

- `get` checks the entries on its key's path only, so a bad entry elsewhere does not
  stop it;
- `keys` checks every entry of the namespace it lists, since its answer depends on all
  of them;
- `commit` checks every entry of every tree it rebuilds, so a bad entry next to a
  changed key is never carried into a new commit.

The error names the key or namespace and the check that failed, never the offending
name or content. The store does not check values: they are bytes, and what they mean
is the caller's.

**Repairing a corrupt branch takes plain git.** Since a commit refuses to rebuild a tree
holding a bad entry, even a commit that only removes it (`without("bad/link")`) is
`StoreError(CORRUPT)`. An operator repairs the branch with an ordinary git commit and a
fast-forward push, after which the store reads it normally.

## 5. Committing

1. **Check the arguments.** The snapshot must come from this store object, and the
   message must hold no NUL character; else `ValueError`, even if nothing would change.
2. **Build the new tree.** Only trees on the path of a changed key are rebuilt, deepest
   first, and each is listed and checked in full (§4) first; every other entry keeps its
   object id, so untouched namespaces are never listed. This is why a commit's cost
   grows with the namespaces on its keys' paths. New values are written with
   `git hash-object -w --stdin`, new trees with `git mktree -z`. Trees left empty are
   dropped.
3. **Stop if nothing changed.** If the new root tree is the commit's tree (the empty
   tree for a store never committed to), the snapshot it derives from is returned, as
   the README describes.
4. **Make the commit.**
   `git -c user.useConfigOnly=true commit-tree <tree> [-p <revision>] -F -` with the
   message on stdin. git takes the author from its configuration; with
   `user.useConfigOnly` it never invents one from the account and host name, and a
   missing identity is `StoreError(NO_IDENTITY)`. `commit-tree` signs nothing
   (`commit.gpgSign` does not apply to it).
5. **Publish it by compare-and-swap.**
   ```
   git push --porcelain --no-verify --no-follow-tags --force-with-lease=refs/heads/<branch>:<revision> -- <remote> <new>:refs/heads/<branch>
   ```
   For a store never committed to, the lease is `refs/heads/<branch>:` (the branch must
   not exist). The lease makes git refuse the push unless the remote's branch is
   exactly `revision`; the new commit's parent is `revision`, so a push that passes the
   lease is also a fast-forward, and compare-and-swap holds even on a remote that allows
   forced pushes. `--no-follow-tags` keeps `push.followTags` from adding tags.
6. **Read the outcome** (below).
7. **Afterwards, best effort:** move the private ref to the new commit
   (`git update-ref <private ref> <new>`), and run `git gc --auto --quiet`. Failures
   here are ignored: the commit is published, and the next snapshot repairs the private
   ref.

### Push outcomes

`--porcelain` prints a status line per ref. The outcome is read from that line, never
from git's wording; there must be exactly one, for `refs/heads/<branch>`.

| What happened | Evidence | Result |
|---|---|---|
| Accepted | our status line, flag `*` (new branch), ` ` (fast-forward) or `+` (forced) | success |
| Already there (defensive: the remote already holds the new commit) | flag `=` | success |
| Our lease failed | flag `!`, `[rejected] (stale info)` | `StaleSnapshot` |
| Not a fast-forward (defensive: the lease forces the push, so git should report the lease instead) | flag `!`, `[rejected] (non-fast-forward)` or `(fetch first)` | `StaleSnapshot` |
| Any other `[rejected]` | flag `!` | `StoreError(REFUSED)` |
| Refused by the remote | flag `!`, `[remote rejected] (…)`; then `ls-remote` (as in §3) | the branch is the new commit: success; the branch moved to anything else: `StaleSnapshot`; the branch is still `revision`, or is gone: `StoreError(REFUSED)`; `ls-remote` fails: `StoreError` with its category |
| No usable status (no line, several lines, or one for another ref) after a failure that sends nothing (`AUTH`, `NOT_FOUND`) | the push's category (§8) | `StoreError` with that category |
| No usable status after any other failure (the connection broke, a timeout, an unrecognised error) | | `UnknownOutcome` |

The remote's reason inside `[remote rejected] (…)` is never parsed: a server can write
anything there. Only whether the branch moved decides.

Why no `ls-remote` after a broken connection: the server applies an update once it has
the pack and the commands, even if the client is gone, so a commit can land *after* an
`ls-remote` that saw `revision`. Nothing short of a later snapshot can settle it, so the
store says it does not know.

## 6. Running git

Every command is run as an argument list, never through a shell, as
`git -C <repo> -c core.hooksPath=/dev/null <command> …`, with remote names after `--`.
No command reads or writes a working tree or the index. The environment is the
caller's, except that:

- variables that would point git at other repository data (another git directory,
  object store, index, graft, shallow or replace data, or ref namespace) are removed;
- the caller's configuration, authentication and identity variables are kept (CI
  injects credentials through them); the store's own `-c` settings come after them and
  win;
- git never prompts, local commands never fetch missing objects, replace objects are
  ignored, and messages are untranslated (to categorise failures, §8).

The exact lists are in `state_store/runner.py`.

`core.hooksPath=/dev/null` turns every hook off. Plumbing commands run none, but
`fetch`, `update-ref` and `push` can run hooks; turning hooks off once is simpler than
reasoning per command (`--no-verify` on `push` is redundant).

**The minimum git version is 2.15**, set by the newest option the store relies on:
`rev-parse --is-shallow-repository`. Below that, `core.hooksPath` (2.9) is a security
floor: an older git ignores the setting and would run hooks. No minimum is tested yet:
CI runs a recent git.

## 7. Opening a store

`GitStateStore(repo, remote=…, branch=…)` checks, without contacting the remote:

- `branch` does not start with `refs/` or `-`, is not `@` or `HEAD`, holds no `@{`,
  and `git check-ref-format refs/heads/<branch>` accepts it (which alone would accept
  `-x` and `HEAD`); `remote` is non-empty, holds only `A-Z a-z 0-9 . _ -` and does not
  start with `-`. Else `ValueError`.
- `repo` is the top level of a non-bare repository (`git rev-parse
  --is-bare-repository` is `false`, and `git rev-parse --show-toplevel` is `repo`,
  both compared after resolving symlinks, so `-C` never walks up into an enclosing
  repository), not shallow (`git rev-parse --is-shallow-repository`) and not partial:
  no remote has `promisor` set to true (`git config --bool --get-regexp
  '^remote\..*\.promisor$'`, each value checked, since an explicit `false` is listed
  too) and there is no `extensions.partialClone` (which older versions of git wrote).
- `remote` is configured with exactly one URL (`git config --get-all
  remote.<remote>.url`), no `remote.<remote>.pushurl`, and `git remote get-url <remote>`
  equals `git remote get-url --push <remote>` (no `insteadOf` / `pushInsteadOf` making
  them differ). With several URLs, git pushes to each and reports the last, so a commit
  can land on one server while the outcome says it was stale; with a separate push URL,
  `ls-remote` would check a different server from the one pushed to.

Any of the last two failing is `StoreError(NOT_A_CLONE)`.

## 8. Errors and the operator log

A failed git command becomes a `StoreError`. For the commands that talk to the remote
(`fetch`, `push`, `ls-remote`), the category comes from git's own wording; anything
unrecognised is `UNRECOGNISED`. A server can imitate git's wording, so it chooses at
most the category, never the text. Local commands have their own, shorter list, ending
in `LOCAL`, so a local "Permission denied" is never mistaken for a remote refusing
access. The wordings are in `state_store/runner.py`.

An error's message names the operation and the category only, and nothing the store
raises carries git's or the server's text, not even in a printed traceback.

git's text goes to `<git dir>/state-store/git-errors.log` instead: appended under a
header line, with every non-printable character but tab escaped and each line prefixed
with `| ` so no line can pass for a header. A log that would pass 1 MiB is first moved
to `git-errors.log.1`. The log may quote the server or the remote's URL (see the
README's requirements on credentials). Logging never fails an operation.

## 9. Concurrency within one clone

Two processes fetching in one clone at once can fail to lock the private ref
(`StoreError(LOCAL)`); nothing is corrupted, and no wrong state is ever reported,
because every commit is still a compare-and-swap on the remote. Within one process,
snapshots and stores are not thread-safe.

## 10. Open questions

- **`keys` and nested namespaces.** `keys` lists values only. No caller needs to list
  namespaces yet; add it if one does.
- **The size limits.** `MAX_VALUE_SIZE` (1 MiB) and the key limits are fixed constants;
  callers keep their own, smaller limits.
