# state-store: design

How `GitStateStore` maps the interface in the [README](README.md) onto git. The README
states what the store promises; this document states how it keeps the promise.

## 1. Layout on the branch

| Store | Git |
|---|---|
| value | a blob, entry mode `100644` |
| namespace | a tree, entry mode `040000` |
| key `a/b/c` | the path `a/b/c` in the commit's tree |
| store state | the tree of the branch's tip commit |
| store never committed to | the branch does not exist (`revision = None`) |
| store emptied | a commit whose tree is the empty tree |

Nothing else is written, and nothing else is accepted on reading (§5). Git does not
store empty trees, which is why a namespace disappears with its last value.

## 2. Taking a snapshot

```
git fetch --no-tags -- <remote> +refs/heads/<branch>:refs/state-store/<remote>/<branch>
git rev-parse --verify --quiet refs/state-store/<remote>/<branch>^{commit}
```

The branch is fetched into a **private ref** that only this package writes. There is
no local branch: the remote is the truth, and the private ref is only where the last
fetch landed. The forced refspec (`+`) is safe because nothing but this package writes
the private ref. (Private refs follow git's ref naming, so one clone cannot hold stores
for both a branch `x` and a branch `x/y`; use one clone per store.)

If the fetch fails, one `git ls-remote -- <remote> refs/heads/<branch>` decides, its
output compared with the exact ref name (`ls-remote` matches patterns on the end of a
name, so `refs/heads/x` also matches `refs/foo/refs/heads/x`):

- the remote lists no such branch: the snapshot is of a store never committed to
  (`revision = None`);
- it lists the branch (created since the fetch looked): fetch once more; a second
  failure is a `StoreError` with the fetch's category;
- `ls-remote` fails too: a `StoreError` with its category.

The snapshot holds the commit id. All of its reads go to that commit, whose objects
never change, which is guarantee 1. Reads are lazy: taking a snapshot transfers objects
but reads none.

**Old snapshots stay readable** while git keeps their objects. Once the private ref has
moved on, an older commit's objects are unreachable, and git only prunes those older
than `gc.pruneExpire` (two weeks by default). Snapshots are meant to live for one
decision, seconds, not weeks.

## 3. Reading

Trees are walked by id from the root, never addressed as `<commit>:<path>` (which fails
for a missing path, and would mean telling that failure apart from others):

| Step | Git |
|---|---|
| the root tree | `git rev-parse <commit>^{tree}` |
| list a namespace | `git ls-tree -l -z <tree id>` |
| read a value | `git cat-file blob <blob id>` |

The git store turns each listed line into a store-neutral `Entry`: its name, its kind
(value for `100644 blob`, namespace for `040000 tree`, *none* for anything else), a
value's size, and its object id. Everything after that (the checks in §5, the overlay,
the caches) is shared code in `snapshot.py`, which the memory store uses too.

Each tree is listed at most once per taken snapshot, and values are read at most once
(`CachedBase`, shared by every snapshot derived from it), so `get` and `keys` on the
same namespace share one listing.

`get("a/b/c")` lists the root, `a` and `a/b` (each once per snapshot), checks the
entries on that path (§5), and finds `c`. A missing segment, or a segment that is a
value where a namespace is needed, means there is no value: `None`. A value's size is
checked from the listing before the blob is read. `keys("a/b")` walks to `a/b` the same
way (nothing there: `[]`), lists it, and checks every entry in it.

## 4. Derived snapshots

A derived snapshot is the snapshot it came from plus an **overlay**: a mapping from key
to new value, or to *removed*. `with_value` and `without` copy the overlay with one more
entry; nothing is written in git. All snapshots derived from one taken snapshot share
its commit id (`revision`), its store, and its listing and value caches.

Reads look in the overlay first and fall back to the commit. `keys(ns)` merges the
commit's values directly in `ns` with the overlay's: added keys appear, removed ones
disappear, nested keys do not count.

Collisions are checked when a change is made, against the merged view: `with_value(k)`
raises `KeyCollision` if any proper prefix of `k` is a value, or if `k` is a namespace
that still holds a value. This reads the commit lazily, so it can raise `StoreError`.
`without(k)` reads nothing and never fails on a valid key: removing a key that has no
value (a namespace, or nothing at all) changes nothing.

`changes` is the overlay as given. Whether it changes anything is only known at commit
(§6).

## 5. Checks on what is read

An entry in a listed tree is valid when:

- its name is a valid key segment ([README](README.md), *Keys*);
- it is a value (`100644 blob`) or a namespace (`040000 tree`): an `Entry` whose kind
  is not *none*;
- a blob's size, from the listing, is at most `MAX_VALUE_SIZE`;
- no other entry in the same tree has the same name (`git mktree` accepts duplicates,
  so a forged tree can hold them).

Anything else (`100755`, `120000` symlinks, `160000` submodules, other names, repeated
names, oversized blobs) is `StoreError(CORRUPT)` for any read that touches it:

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

## 6. Committing

1. **Check the arguments.** The snapshot must come from this store object, and the
   message must hold no NUL character; else `ValueError`, even if nothing would change.
2. **Build the new tree.** Only trees on the path of a changed key are rebuilt, deepest
   first, and each is listed and checked in full (§5) first; every other entry keeps its
   object id, so untouched namespaces are never listed. New values are written with
   `git hash-object -w --stdin`, new trees with `git mktree -z`. Trees left empty are
   dropped.
3. **No change, no commit.** If the new root tree is the commit's tree (the empty tree
   when `revision` is `None`), nothing changed: the snapshot it derives from is
   returned, and the remote is not contacted. This is the rule in the
   [README](README.md) that a snapshot changing nothing commits nothing and checks
   nothing.
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

The new snapshot returned has `revision` = the new commit and no changes.

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
| Refused by the remote | flag `!`, `[remote rejected] (…)`; then `ls-remote` (as in §2) | the branch is the new commit: success; the branch moved to anything else: `StaleSnapshot`; the branch is still `revision`, or is gone: `StoreError(REFUSED)`; `ls-remote` fails: `StoreError` with its category |
| No usable status (no line, several lines, or one for another ref) after a failure that sends nothing (`AUTH`, `NOT_FOUND`) | the push's category (§9) | `StoreError` with that category |
| No usable status after any other failure (the connection broke, a timeout, an unrecognised error) | | `UnknownOutcome` |

The remote's reason inside `[remote rejected] (…)` is never parsed: a server can write
anything there. Only whether the branch moved decides.

Why no `ls-remote` after a broken connection: the server applies an update once it has
the pack and the commands, even if the client is gone, so a commit can land *after* an
`ls-remote` that saw `revision`. Nothing short of a later snapshot can settle it, so the
store says it does not know.

## 7. Running git

Every command is run as an argument list, never through a shell:

```
git -C <repo> -c core.hooksPath=/dev/null <command> …
```

in an environment that is the caller's, with these changes:

- **Removed:** every variable git lists as local to a repository
  (`git rev-parse --local-env-vars`) that would make it read other repository data:
  `GIT_DIR`, `GIT_WORK_TREE`, `GIT_IMPLICIT_WORK_TREE`, `GIT_PREFIX`, `GIT_COMMON_DIR`,
  `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`,
  `GIT_GRAFT_FILE`, `GIT_SHALLOW_FILE`, `GIT_REPLACE_REF_BASE`, `GIT_CONFIG`,
  `GIT_NO_REPLACE_OBJECTS` (set again below), and `GIT_NAMESPACE` (not listed, but it
  changes which refs git sees).
- **Kept:** the caller's configuration variables (`GIT_CONFIG_PARAMETERS`,
  `GIT_CONFIG_COUNT` and its keys: how CI injects credentials), authentication
  (`GIT_SSH_COMMAND`, `GIT_ASKPASS`, …) and identity (`GIT_AUTHOR_NAME`, …). The store's
  own `-c` settings come after inherited configuration and win (verified with git 2.53
  for both variables).
- **Set:** `GIT_TERMINAL_PROMPT=0` (never prompt for credentials), `GIT_NO_LAZY_FETCH=1`
  (local commands never contact the remote; git 2.44 and later, harmless before),
  `GIT_NO_REPLACE_OBJECTS=1` (no `refs/replace/` object may stand in for what the branch
  holds) and `LC_ALL=C` (untranslated messages, for categorising failures).

Remote names always come after `--`.

`core.hooksPath=/dev/null` turns every hook off. Plumbing commands run none, but
`fetch`, `update-ref` and `push` can run `reference-transaction` and `pre-push` hooks;
turning hooks off once is simpler than reasoning per command. (`--no-verify` on `push`
is belt and braces.) git 2.53 has no hooks configured outside `core.hooksPath`; check
again when the minimum git version moves.

**The minimum git version is 2.15**, set by the newest option the store relies on:
`rev-parse --is-shallow-repository` (2.15). Below it, `core.hooksPath` (2.9) is a hard
security floor: an older git silently ignores the setting and would run hooks. The
other options are older still (`user.useConfigOnly` 2.8, `remote get-url` 2.7,
`push --force-with-lease`), except `GIT_NO_LAZY_FETCH` (2.44), which older versions
ignore harmlessly since partial clones are refused. No minimum is tested yet: CI runs a
recent git.

## 8. Opening a store

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
  too) and there is no `extensions.partialClone` (which git 2.53 no longer writes, but
  older versions did).
- `remote` is configured with exactly one URL (`git config --get-all
  remote.<remote>.url`), no `remote.<remote>.pushurl`, and `git remote get-url <remote>`
  equals `git remote get-url --push <remote>` (no `insteadOf` / `pushInsteadOf` making
  them differ). With several URLs, git pushes to each and reports the last, so a commit
  can land on one server while the outcome says it was stale; with a separate push URL,
  `ls-remote` would check a different server from the one pushed to.

Any of the last two failing is `StoreError(NOT_A_CLONE)`.

## 9. Errors and the operator log

A failed git command becomes a `StoreError`. For the commands that talk to the remote
(`fetch`, `push`, `ls-remote`), the category comes from git's own wording (with
`LC_ALL=C`), first match wins:

| Category | git says |
|---|---|
| `NOT_A_CLONE` | `not a git repository (or any of the parent`, `cannot change to` |
| `AUTH` | `Authentication failed`, `Permission denied`, `could not read Username`, `could not read Password`, `terminal prompts disabled`, `returned error: 401`, `returned error: 403`, `Host key verification failed` |
| `NOT_FOUND` | `Repository not found`, `does not appear to be a git repository`, `returned error: 404` (never a bare `not found` or `No such file or directory`: those also say a program such as `ssh` is missing) |
| `UNREACHABLE` | `Could not resolve host`, `Couldn't resolve host`, `Connection refused`, `timed out`, `Network is unreachable`, `No route to host`, `Connection reset`, `the remote end hung up`, `early EOF`, `unable to access` |
| `UNRECOGNISED` | anything else |

A server can imitate git's wording, so it chooses at most the category, never the text.
For local commands only `NOT_A_CLONE` (the same wording), `NO_IDENTITY` (`Please tell me
who you are`, `empty ident name`) and `LOCAL` (anything else) apply, so a local
"Permission denied" is never mistaken for a remote refusing access.

The message names the operation and the category only. Internally a failure is a
`GitFailure` whose message and arguments hold only the command and the category (git's
output is an attribute, never in `args` or the repr), and the store raises its own
errors `from None`, so not even a printed traceback carries git's or the server's text.

git's text, with every non-printable character but tab escaped and each line prefixed
with `| ` so no line can pass for a header, is appended under a header line to
`<git dir>/state-store/git-errors.log`; a log that would pass 1 MiB is first moved to
`git-errors.log.1`. It may quote the server or the remote's URL, credentials included if the
URL holds them. It is for an operator, but anything that can read the clone can read it,
which is why credentials belong in a credential helper, never in the URL. Logging never
fails an operation.

## 10. Concurrency within one clone

One process at a time per clone. Two processes fetching at once can fail to lock the
private ref (`StoreError(LOCAL)`); nothing is corrupted, and no wrong state is ever
reported, because every commit is still a compare-and-swap on the remote. Within one
process, snapshots and stores are not thread-safe.

## 11. `MemoryStateStore`

The same `StateSnapshot` and `CachedBase` classes, over a different `Base`: a list of
committed states, each a dict from key to value, whose revision is an opaque string;
its listings are built from the dict, so its entries are always valid. It follows the same rules
as `GitStateStore`, in the same order: a snapshot from another store object is a
`ValueError`; a snapshot that changes nothing returns the snapshot it derives from
without any freshness check; otherwise the commit lands if the snapshot's revision is
the latest, else `StaleSnapshot`; emptying the store makes a new revision, not `None`.
It never raises `StoreError` or `UnknownOutcome` by itself. Sharing `StateSnapshot`, and
running `src/state-store/tests/test_contract.py` against both stores, keeps the semantics identical.

## 12. Git commands used

`fetch`, `ls-remote`, `rev-parse`, `ls-tree`, `cat-file`, `hash-object`, `mktree`,
`commit-tree`, `push`, `update-ref`, `gc`, `config`, `remote get-url`,
`check-ref-format`. No command that reads or writes a working tree or the index.

## 13. Open questions

- **`keys` and nested namespaces.** `keys` lists values only. Whether the ticket layer
  needs to list namespaces is TBD; add it if a caller does.
- **The size limits.** `MAX_VALUE_SIZE` (1 MiB) and the key limits are fixed constants;
  callers keep their own, smaller limits.
