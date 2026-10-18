# state-store decisions

How to write one: [`CONTRIBUTING.md`](../../CONTRIBUTING.md#decision-records).

## Index

| Decision | Status |
|---|---|
| [0001: state-store provides consistent, all-or-nothing shared state without a server](0001-what-state-store-provides.md) | accepted |
| [0002: Threat model: trust the caller's machine and the remote's branch protection](0002-threat-model.md) | accepted |
| [0003: The store is files at the tip of one git branch](0003-state-is-files-at-the-tip-of-one-git-branch.md) | accepted |
| [0004: A key/value interface of immutable snapshots and compare-and-swap commits](0004-snapshots-and-compare-and-swap-commits.md) | accepted |
| [0005: Corrupt state stops the operation that reads it](0005-corrupt-state-stops-the-operation-that-reads-it.md) | accepted |
