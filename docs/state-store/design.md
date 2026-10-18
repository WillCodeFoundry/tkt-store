# state-store: design

How the stores keep the promises the [README](README.md) makes. Section 1 applies to
both stores; the rest is about the git store.

## 1. Snapshots and changes

Each store supplies a read-only view of one committed state: it lists a namespace's
entries (each one's name, whether it is a value or a namespace, a value's size, and
whether a namespace is empty) and reads a value. Everything else is common to both
stores, in one implementation
([0004](decisions/0004-use-immutable-snapshots-and-compare-and-swap-commits.md)): the
checks on what is read, the merging of changes, and remembering what was read.

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
is a namespace that still holds a value. Telling whether `k` still holds a value, once
the changes are applied, can mean listing `k` and the namespaces inside it. This reads
the committed state, so it can raise `StoreError`. `without(k)` reads nothing and never
fails on a valid key.

**Checks on what is read.** An entry of a listed namespace is valid when:

- its name is a valid key segment ([README](README.md#keys));
- it is a value or a namespace, and nothing else;
- a value's size, from the listing, is at most `MAX_VALUE_SIZE`;
- no other entry in the same namespace has the same name;
- it is not an empty namespace (the store never writes one).

Anything else is `CorruptState` for any operation that touches it:

- `get` and `with_value` check the entries on their key's path, so a bad entry
  elsewhere does not stop them; a collision check also checks in full every namespace
  it lists inside the key;
- `keys` checks every entry of the namespace it lists, since its answer depends on all
  of them;
- `commit` checks every entry of every namespace it rebuilds, so a bad entry next to a
  changed key is never carried into a new commit.

The error names the check that failed ([README](README.md#errors)). The store does
not check values: they are bytes, and what they mean is the caller's.

**A commit** first checks its arguments, then works out whether the snapshot changes
anything (a change can set a value a key already has); only then does it publish, by
compare-and-swap on the revision the snapshot was taken at. `changes` is the mapping as
given, so it can hold changes that change nothing.

**`MemoryStateStore`** keeps its committed states as a list of mappings from key to
value, each with an opaque revision; it starts with one, empty. Its listings are built
from the mapping, so they are always valid. Its commit follows the same steps as the
git store's, in the same order: emptying the store makes a new revision. The same
contract tests run against both stores.

## 2. Layout on the branch

| Store | Git |
|---|---|
| value | a blob, entry mode `100644` |
| namespace | a tree, entry mode `040000` |
| key `a/b/c` | the path `a/b/c` in the commit's tree |
| committed state | the tree of the branch's tip commit |
| revision | the tip commit's id |
| store emptied, or new | a commit whose tree is the empty tree |

Nothing else is written, and nothing else is accepted on reading (§1, §4). The store
drops trees left empty (§5), which is why a namespace disappears with its last value;
the root is the only tree that can be empty.

## 3. Taking a snapshot and reading

```
git fetch --no-tags -- origin +refs/heads/<branch>:refs/remotes/origin/<branch>
git rev-parse --verify --quiet refs/remotes/origin/<branch>^{commit}
```

`origin` is the clone's one remote (§7). The branch is fetched into the **tracking
ref**, `refs/remotes/origin/<branch>`, the ref `git clone` made for it; the refspec is
given in full, and is the one the clone's configuration holds (§7), so the fetch writes
no other ref. The tracking ref names the commit just fetched, keeps that commit's
objects from being pruned, and tells the next fetch what the clone already has, so only
new objects are transferred. Only state-store moves it, so the forced refspec (`+`) is
safe. It is not the truth, the remote is: the next fetch corrects a stale tracking
ref.

If the fetch fails, one `git ls-remote -- origin refs/heads/<branch>` decides, its
output compared with the exact ref name (`ls-remote` matches patterns on the end of a
name, so `refs/heads/x` also matches `refs/foo/refs/heads/x`):

- the remote lists no such branch: `NoSuchBranch` (the branch existed when the clone
  was made, so it has been deleted, against the preconditions);
- it lists the branch (created since the fetch looked): fetch once more; a second
  failure is `RemoteFailed`;
- `ls-remote` fails too: `RemoteFailed`.

The snapshot holds the commit id, and all of its reads go to that commit, whose objects
never change: that is guarantee 1. Taking a snapshot transfers objects but reads none.

**The last commit is checked.** The store object remembers the outcome of its last
commit (§5), and the next snapshot it takes checks it against the fetched tip, then
forgets it. Under the preconditions the branch only moves forward, so:

- a published commit stays in the branch's history: it must be the tip or one of its
  ancestors (`git merge-base --is-ancestor <last> <tip>`);
- a failed compare-and-swap means the branch had already moved from the revision the
  lease expected: the tip must not be that revision.

Either check failing means pushes reach a repository the store does not fetch from,
such as another repository a push URL rewrite points to, and the snapshot fails with
`PushElsewhere`. Without the second check, a store pushing to a repository that is not
at the snapshot's revision would see every compare-and-swap fail, and its callers
would start again forever. The checks cost nothing on the network, but only cover
commits the same store object takes a snapshot after: the last commit before a process
exits is never checked. A caller always takes a snapshot after `CompareAndSwapFailed`,
so a failed compare-and-swap is always checked.

Reading walks trees by id from the root, never addressing `<commit>:<path>` (which fails
for a missing path, and would mean telling that failure apart from others):

| Step | Git |
|---|---|
| the root tree | `git rev-parse <commit>^{tree}` |
| list a namespace | `git ls-tree -l -z <tree id>` |
| read a value | `git cat-file blob <blob id>` |

`get("a/b/c")` lists the root, `a` and `a/b`, checks the entries on that path (§1), and
finds `c`. A missing segment, or a segment that is a value where a namespace is needed,
means there is no value: `None`. A value's size is checked from the listing before the
blob is read. `keys("a/b")` walks to `a/b` the same way (nothing there: `[]`), lists
it, and checks every entry in it.

**Old snapshots stay readable.** Under the preconditions the branch only moves
forward, so every revision a snapshot was taken at stays reachable from the tracking
ref, and git never prunes its objects. The one exception is brief: a commit whose
tracking ref update failed (§5, step 7) is unreachable until the next fetch, and git
prunes only while fetching, after it has moved the tracking ref (§6).

## 4. Corrupt entries in git

The git store lists a tree entry as a value only for `100644 blob`, and as a namespace
only for `040000 tree`; anything else (`100755` executables, `120000` symlinks,
`160000` submodules) is neither, so the checks in §1 reject it. A forged tree can also
hold repeated names or empty subtrees, since `git mktree` accepts both. The empty tree
has one fixed id for each object format (the store asks git for it once,
`git hash-object -t tree /dev/null`), so an empty subtree is recognised from its
parent's listing, without listing it.

**Repairing a corrupt branch takes plain git.** Since a commit refuses to rebuild a tree
holding a bad entry, even a commit that only removes it (`without("bad/link")`) is
`CorruptState`. With writers stopped, an operator repairs the branch with an
ordinary git commit and a fast-forward push, after which the store reads it normally.

## 5. Committing

1. **Check the arguments.** The snapshot must come from this store object, and the
   message must hold no NUL character; else `ValueError`, even if nothing would change.
2. **Build the new tree.** Only trees on the path of a changed key are rebuilt, deepest
   first, and each is listed and checked in full (§1) first; every other entry keeps its
   object id, so untouched namespaces are never listed. This is why a commit's cost
   grows with the namespaces on its keys' paths. New values are written with
   `git hash-object -w --stdin`, new trees with `git mktree -z`. Trees left empty are
   dropped.
3. **Stop if nothing changed.** If the new root tree is the commit's tree, the
   snapshot it derives from is returned, as the README describes.
4. **Make the new commit, `<new>`.** First
   `git -c user.useConfigOnly=true var GIT_AUTHOR_IDENT` and `… var GIT_COMMITTER_IDENT`
   check that git has an identity: if either fails, `NoIdentity`. Then
   `git -c user.useConfigOnly=true commit-tree <tree> -p <revision> -F -` with the
   message on stdin. git takes the author from its configuration; with
   `user.useConfigOnly` it never invents one from the account and host name.
   `commit-tree` signs nothing (`commit.gpgSign` does not apply to it).
5. **Publish it by compare-and-swap.**
   ```
   git push --porcelain --no-follow-tags --force-with-lease=refs/heads/<branch>:<revision> -- origin <new>:refs/heads/<branch>
   ```
   The lease makes git refuse the push unless the remote's branch is exactly
   `revision`; the new commit's parent is `revision`, so a push that passes the
   lease is also a fast-forward, and compare-and-swap holds even on a remote that allows
   forced pushes. `--no-follow-tags` keeps `push.followTags` from adding tags.
6. **Read the outcome** (below). For the next snapshot's check (§3), remember `<new>`
   on success, and `revision` on a `CompareAndSwapFailed`; an `UnknownOutcome`
   remembers nothing, since the commit may or may not have landed.
7. **Afterwards, best effort:** move the tracking ref to `<new>`
   (`git update-ref refs/remotes/origin/<branch> <new>`). A failure here is ignored:
   the commit is published, and the next snapshot corrects the tracking ref.

### Push outcomes

`--porcelain` makes the local git print a status line per ref. The outcome is read
from that line's flag and git's own fixed summary (`[rejected] (stale info)` and the
like), never from the remote's reason; there must be exactly one line, for
`refs/heads/<branch>`.

| What happened | Evidence | Result |
|---|---|---|
| Accepted | our status line, flag ` ` (fast-forward) or `+` (forced) | success |
| Already there (defensive: the remote already holds the new commit) | flag `=` | success |
| Our lease failed | flag `!`, `[rejected] (stale info)` | `CompareAndSwapFailed` |
| Not a fast-forward (defensive: the lease forces the push, so git should report the lease instead) | flag `!`, `[rejected] (non-fast-forward)` or `(fetch first)` | `CompareAndSwapFailed` |
| Any other `[rejected]` | flag `!` | `CommitRefused` |
| Refused by the remote | flag `!`, `[remote rejected] (…)`; then `ls-remote` (as in §3) | the branch is the new commit: success; the branch is still `revision`, or is gone: `CommitRefused`; the branch moved to anything else: fetch it into the tracking ref, then success if the new commit is an ancestor of its tip (`git merge-base --is-ancestor`), else `CompareAndSwapFailed`; `ls-remote` or that fetch fails: `UnknownOutcome` |
| The remote did not report a status | flag `!`, `[remote failure]` | `UnknownOutcome` |
| No usable status (no line, several lines, or one for another ref), whatever the failure | | `UnknownOutcome`: if nothing was sent (bad credentials, no such repository), the caller's next snapshot fails with `RemoteFailed` |

The remote's reason inside `[remote rejected] (…)` is never parsed: a server can write
anything there. Only where the branch is decides: a server's `update` hook runs after
the pushed objects are stored, so it can apply the update and still report a refusal,
and another writer can then commit on top before the store looks. Checking ancestry
tells that apart from a lost race, so a `CompareAndSwapFailed` always means nothing was
published.

Why no `ls-remote` after a broken connection: the server applies an update once it has
the pack and the commands, even if the client is gone, so a commit can land *after* an
`ls-remote` that saw `revision`. Nothing short of a later snapshot can settle it, so the
store says it does not know.

## 6. Running git

Every command is run as an argument list, never through a shell, as
`git -C <path> -c core.hooksPath=/dev/null -c maintenance.autoDetach=false
-c gc.autoDetach=false <command> …`, where `<path>` is the clone (or, while cloning,
the temporary directory, §7). The clone is not bare, so `-C` works whatever the
user's `safe.bareRepository` says. `GIT_CEILING_DIRECTORIES` is set to the directory
holding the clone, so git never searches above it for a repository: an enclosing
repository's configuration never applies, even in the temporary directory, which is
not yet a repository. No command reads or writes a working tree or the index. The
environment is the caller's, except that:

- variables that would point git at other repository data (another git directory,
  object store, index, graft, shallow or replace data, or ref namespace) are removed;
- the caller's configuration, authentication and identity variables are kept (CI
  injects credentials through them); the store's own `-c` settings come after them and
  win;
- git never prompts, local commands never fetch missing objects, replace objects are
  ignored, and messages are untranslated (for the operator log, §8).

The exact lists are in `state_store/runner.py`.

`core.hooksPath=/dev/null` turns every hook off. `fetch` (with the maintenance it
starts), `update-ref` and `push` can run hooks, and the other commands run none;
turning hooks off once is simpler than reasoning per command.

**Housekeeping is git's.** Each commit writes a few loose objects, and lost races leave
unreachable ones. A successful `fetch` runs git's automatic maintenance afterwards, which
packs objects and prunes unreachable ones older than two weeks once enough have built
up. Every snapshot fetches, so the store runs no `gc` of its own. The two `autoDetach`
settings keep that maintenance in the foreground (git reads `maintenance.autoDetach`
first, and older versions only `gc.autoDetach`), so no git process outlives the command
that started it, and nothing runs in the clone between the store's commands.

**The minimum git version** ([README](README.md#git-store)) is set by the newest option
the store relies on: `git clone --no-tags` (§7). It is also above 2.9, the
version that added `core.hooksPath`, which the store needs to turn hooks off. No
minimum is tested yet: CI runs a recent git.

## 7. Cloning and opening

The store makes the clone it works in, and opens only clones it made
([0006](decisions/0006-let-the-store-make-its-own-clone.md)).

**Cloning**, `GitStateStore.clone(path, url=…, branch=…)`, first checks its arguments:
`branch` follows the README's rules and `url` is not empty, else `ValueError`. Whether
git accepts the branch is asked of `git check-ref-format refs/heads/<branch>`, which
alone would accept the `refs/…`, `-…`, `@` and `HEAD` forms, hence the README's other
rules. It makes `path` absolute, so later commands do not depend on the working
directory, and refuses a `path` where anything exists, even a broken symlink, with
`UnusableRepository`. Then:

1. make a new temporary directory next to `path`, named `.<name>.state-store-<random>`
   after `path`'s last component `<name>`;
2. clone into it:
   ```
   git clone --quiet --no-checkout --single-branch --branch <branch> --no-tags
             --origin origin --template= -- <url> .
   ```
   With no template, nothing from the user's template directory (hooks, or a `config`
   file, which git copies) gets in; `--origin` keeps the user's
   `clone.defaultRemoteName` from naming the remote otherwise. The clone takes the
   remote's object format. It
   holds the tracking ref `refs/remotes/origin/<branch>` (§3), a local branch, and, as
   `origin`'s settings, the URL, the fetch refspec
   `+refs/heads/<branch>:refs/remotes/origin/<branch>` and `tagopt = --no-tags`;
3. if the clone fails, one `git ls-remote -- <url> refs/heads/<branch>` decides, its
   output compared with the exact ref name, as in §3: the remote lists no such branch:
   `NoSuchBranch`; it lists it, or `ls-remote` fails too: `RemoteFailed`;
4. delete the local branch (`git update-ref -d refs/heads/<branch>`), so the tracking
   ref is the only copy of the branch in the clone (HEAD then names a branch that does
   not exist, and `branch.<branch>.*` settings stay; nothing reads either), and set
   `state-store.branch` to `branch` (`git config -- state-store.branch <branch>`);
5. rename the directory to `path`;
6. open it, as below, and return the store.

Any other failure in steps 1 to 5 is `UnusableRepository`. On a failure in steps 2 to
5 the store removes the temporary directory; a crash leaves it, for an operator to
remove. Commands run while cloning log nothing (§8): the log would be inside the
temporary directory, and writing it there could make the directory look like a
repository to the next command. Either way there is never a half-made clone at `path`.
A clone that fails step 6 stays at `path` and is refused like any other. Another
process cloning to `path` at the same time breaks the one-process requirement: the
rename then fails, or, if `path` is an empty directory, replaces it.

**Opening**, `GitStateStore(path)`, makes `path` absolute and checks, without
contacting the remote:

- `path` is the top level of a non-bare repository: `git rev-parse
  --is-bare-repository` is `false`, and `git rev-parse --show-toplevel` is `path`, both
  compared after resolving symlinks (a subdirectory of a clone is refused);
- `state-store.branch` has exactly one value (`git config --get-all`), a branch name
  that passes the checks made when cloning: the store's branch;
- the settings of `origin`, in every configuration file git reads (the user's
  included), are those the clone was made with, plus at most one push URL:
  `git config --get-regexp '^remote\.origin\.'` lists one `url`, the fetch refspec
  for the store's branch, `tagopt = --no-tags`, at most one `pushurl`, and nothing
  else. With several URLs or push URLs, git pushes to each and reports each, so a
  commit can land on one server and be refused by another; another fetch refspec would
  make fetches write other refs (§3). The one `url` is the store's URL.

A `pushurl`, and the user's URL rewriting (`insteadOf`, `pushInsteadOf`), are not
checked further: they may fetch and push the same repository by different URLs
(HTTPS to fetch, SSH to push). One that sends pushes to another repository shows at
the next snapshot (§3).

Any check failing, including git failing to run it, is `UnusableRepository`.

## 8. Errors and the operator log

The kind of error never depends on git's text, which varies between versions and
transports, can describe a local or a remote problem in the same words, and can come
from the server. It depends only on what the store can tell for certain: its own
checks (`CorruptState`, `UnusableRepository`, `NoIdentity`, `PushElsewhere`), the
push's status line and where the branch is (`CompareAndSwapFailed`, `CommitRefused`,
`UnknownOutcome`), and which command failed: `RemoteFailed` for cloning, fetching, or
checking whether the branch exists (§3, §7), `NoSuchBranch` when that check finds no
branch, and `GitFailed` for any other command, except one run to make the clone or as
one of the store's checks, whose failure is that step's outcome (§7:
`UnusableRepository`; §5, step 4: `NoIdentity`).

The README's rule on what an error's message holds applies to everything the store
raises, even in a printed traceback. git's text goes to
`<path>/.git/state-store/git-errors.log` instead (nothing is logged while cloning,
§7): appended under a header line, with every non-printable character but tab escaped
and each line prefixed with `| ` so no line can pass for a header. A log that would
pass 1 MiB is first moved to `git-errors.log.1`. The log may quote the server or the
remote's URL (see the README's requirements on credentials). Logging never fails an
operation.

## 9. Concurrency within one clone

Two processes fetching in one clone at once can fail to lock the tracking ref
(`RemoteFailed`, since it happens in `fetch`); nothing is corrupted, and no wrong state
is ever reported, because every commit is still a compare-and-swap on the remote.
Within one process, snapshots and stores are not thread-safe.

## 10. Open questions

- **A failed clone's log.** The temporary directory, with git's text, is removed when
  cloning fails, so an operator learns only the error's kind. Keep the text somewhere
  if operators need it.
- **Hooks defined elsewhere.** The store assumes git finds hooks only through
  `core.hooksPath` (§6). Recheck if git adds another way to define them.
- **`keys` and nested namespaces.** `keys` lists values only. No caller needs to list
  namespaces yet; add it if one does.
