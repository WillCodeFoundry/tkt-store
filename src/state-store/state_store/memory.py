"""`MemoryStateStore`: the same semantics in memory, for tests of code built on the
store (state-store design §1). One instance stands for one store that many writers share."""

from __future__ import annotations

from state_store.snapshot import StateSnapshot


class MemoryStateStore:
    """Committed states kept as a list of dicts; a revision is an opaque string."""

    def __init__(self) -> None:
        raise NotImplementedError

    def snapshot(self) -> StateSnapshot:
        """The latest committed state."""
        raise NotImplementedError

    def commit(self, snapshot: StateSnapshot, message: str) -> StateSnapshot:
        """See `StateStore.commit`. Never raises `StoreError` or `UnknownOutcome`."""
        raise NotImplementedError
