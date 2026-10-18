# 0003: Secrets are stored only as hashes

**Status:** accepted (2026-10-18)

## Context

An agent proves it holds a claim by presenting a secret claim id that it minted. The
store is readable by every agent, so anything written there is visible to all of them.

## Decision

tkt-store never writes a secret in a form that can be recovered: it stores only the
secret's SHA-256 hash, which is enough to check a secret when it is presented. This
holds even once the secret can no longer be used.

## Alternatives rejected

- **Storing the secret itself:** any agent reading the store could act as the holder.
- **Proving identity with git commit signing instead:** it needs a key per agent and a
  list of trusted keys kept outside the store, and a leaked key would expose every
  claim that agent ever makes, where a leaked claim id exposes one claim.
- **Revealing a secret once it is no longer usable:** no use, and needless exposure.

## Consequences

- An agent that loses its secret cannot act on its own claim; how anyone else ends it
  is TBD with the rest of tkt-store's design.
