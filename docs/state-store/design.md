# state-store: design

How the git store keeps the promises in the [README](README.md).

## Layout

| Store | Git |
|---|---|
| value | a blob, mode `100644` |
| namespace | a tree |
| key `a/b/c` | the path `a/b/c` in the tip commit's tree |
| revision | the tip commit's id |
| new or emptied store | a commit of the empty tree |

Trees left empty are dropped, so a namespace disappears with its last value.

## Cloning and opening

`GitStateStore.clone(path, url=…, branch=…)`:

```
git clone --quiet --no-checkout --single-branch --branch <branch> --no-tags -- <url> <path>
git -C <path> config state-store.branch <branch>
```

If the branch does not exist on the remote, cloning fails with `StoreError`.

`GitStateStore(path)` reads the branch from `state-store.branch` and uses the remote
`origin` that `git clone` made; if either is missing, `StoreError`. It contacts
nothing.

## Snapshot

```
git fetch --no-tags -- origin +refs/heads/<branch>:refs/remotes/origin/<branch>
git rev-parse --verify --quiet refs/remotes/origin/<branch>^{commit}
```

The branch is fetched into the tracking ref `git clone` made. The snapshot holds the
commit id; every read goes to that commit, whose objects never change.

## Reading

All local. `get` and `keys` walk trees by id from the root
(`git ls-tree -l -z <tree>`) and read values with `git cat-file blob <id>`. An entry
that is neither a regular blob nor a tree, or whose name is not a valid segment, is
a `StoreError` for the operation that reads it.

## Commit

1. Write new values (`git hash-object -w --stdin`) and rebuild the trees on the paths
   of changed keys, deepest first (`git mktree -z`).
2. If the new root tree is the snapshot's tree, return without committing.
3. `git commit-tree <tree> -p <revision> -F -`, with the message on stdin.
4. Publish by compare-and-swap:
   ```
   git push --porcelain --force-with-lease=refs/heads/<branch>:<revision> -- origin <new>:refs/heads/<branch>
   ```
5. Read the outcome from the status line `--porcelain` prints:

| Status | Result |
|---|---|
| accepted (` ` or `+`) | success |
| `[rejected] (stale info)` | `CompareAndSwapFailed` |
| any other refusal | `StoreError` |
| no status (connection lost) | `UnknownOutcome` |

## Running git

Every command is an argument list, never a shell, run in the clone with
`-c core.hooksPath=/dev/null`, so no hook runs. Variables that would point git at
another repository (`GIT_DIR` and the like) are removed from the environment.

## Open questions

Deferred until the main path runs; each is added only if it turns out to matter.

- A crash while cloning leaves a partial clone at `path`.
- Checks on the clone when opening (several URLs, push URLs, URL rewriting).
- A remote that applies a push and still reports it refused.
- Hardening against the caller's own git configuration and environment beyond
  `GIT_DIR`.
- Where git's own output goes for an operator.
- Finer checks on corrupt entries (duplicates, empty trees, oversized values).
