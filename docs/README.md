# Documentation

Project-wide documents are at the top; each layer of tkt-store has a directory of its
own, with the same three parts: what it promises (`README.md`), how it keeps those
promises (`design.md`), and why it is the way it is (`decisions/`).

| Document | What |
|---|---|
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Where changes are specified, tooling, checks, testing, commit rules |
| [`decisions/`](decisions/README.md) | Decisions that cut across layers, and how to write a decision record |
| **The ticket layer** | |
| [`tkt-store/README.md`](tkt-store/README.md) | What it promises: TBD |
| [`tkt-store/design.md`](tkt-store/design.md) | How it keeps those promises on state-store: TBD |
| [`tkt-store/decisions/`](tkt-store/decisions/README.md) | Its decisions |
| **state-store, the storage layer** | |
| [`state-store/README.md`](state-store/README.md) | What it promises: interface, guarantees, errors, keys |
| [`state-store/design.md`](state-store/design.md) | How it keeps those promises on git |
| [`state-store/decisions/`](state-store/decisions/README.md) | Its decisions |
