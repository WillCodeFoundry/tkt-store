# Decisions

Records of the decisions that shape tkt-store: what was decided, why, and what was
rejected. They explain why something is the way it is; the specification and design
documents say what it is.

## Where a decision goes

- **Here**, in `docs/decisions/`: decisions that cut across layers (how tkt-store is
  built, rules every layer follows).
- **In a layer's own `decisions/`** (`docs/state-store/decisions/`,
  `docs/tkt-store/decisions/`): decisions about that layer only.

## Writing one

- Copy [`template.md`](template.md) to `NNNN-short-title.md`, numbered in sequence
  within its directory (`0001-…`, `0002-…`).
- Add it to its directory's index, below.
- A decision is never edited to say something else: a later decision supersedes it, and
  both say so in their status.
- The specification or design the decision changes is updated in the same change.

## Index

None yet.
