# state-store decisions

How to write one: [`CONTRIBUTING.md`](../../CONTRIBUTING.md#decision-records).

## Index

| Decision | Status |
|---|---|
| [0001: Provide consistent, all-or-nothing shared state](0001-provide-consistent-all-or-nothing-shared-state.md) | accepted |
| [0002: Store keys as paths in the tree of one git branch](0002-store-keys-as-paths-in-the-tree-of-one-git-branch.md) | accepted |
| [0003: Trust only the caller's machine and the remote's handling of pushes](0003-trust-only-the-callers-machine-and-the-remotes-handling-of-pushes.md) | accepted |
| [0004: Use immutable snapshots and compare-and-swap commits](0004-use-immutable-snapshots-and-compare-and-swap-commits.md) | accepted |
| [0005: Fail operations that read corrupt state](0005-fail-operations-that-read-corrupt-state.md) | accepted |
| [0006: Let the store make its own clone](0006-let-the-store-make-its-own-clone.md) | accepted |
| [0007: Check each commit against the branch at the next snapshot](0007-check-each-commit-against-the-branch-at-the-next-snapshot.md) | accepted |
