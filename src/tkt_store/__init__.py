"""tkt-store: a git-backed ticket store for coordinating agents.

Layers (inward-only dependencies; see docs/design.md):
- domain          pure value types, status, operations, rules, outcomes
- application     ports (Store, Clock, IdSource) and the use cases over them
- infrastructure  concrete adapters (git, in-memory, system clock, random ids)
- cli             the interface

This module is the composition root: `open_store(repo)` is the one place that picks
concrete implementations and wires them into a `TicketStore`. It is the only part
of the package that depends on every layer at once — which is exactly what lets
the inner layers stay ignorant of git, the system clock and randomness.
"""

from __future__ import annotations

from pathlib import Path

from tkt_store.application.clock import Clock
from tkt_store.application.errors import (
    Conflict,
    RefusedError,
    RetriesExhausted,
    StoreError,
)
from tkt_store.application.ids import IdSource
from tkt_store.application.service import DEFAULT_TTL, TicketStore, raise_for_refusal
from tkt_store.application.store import HistoryEntry, Store
from tkt_store.application.transaction import Committed, Outcome, Refused, Unchanged
from tkt_store.domain.errors import TktError
from tkt_store.domain.outcomes import Refusal, RefusalCode
from tkt_store.domain.status import Status
from tkt_store.domain.ticket import Claim, Kind, Revision, Stage, Ticket
from tkt_store.infrastructure.clock import FakeClock, SystemClock
from tkt_store.infrastructure.git.repo import GitStore
from tkt_store.infrastructure.git.wire import DEFAULT_REF
from tkt_store.infrastructure.ids import RandomIds, SequentialIds
from tkt_store.infrastructure.memory import MemStore


def open_store(
    repo: Path,
    *,
    ref: str = DEFAULT_REF,
    remote: str | None = None,
    clock: Clock | None = None,
    ids: IdSource | None = None,
) -> TicketStore:
    """Open a ticket store with the production wiring: a GitStore at `repo`, the
    system clock, and random ids.

    `clock` and `ids` can be overridden (e.g. for simulations) but default to the
    real implementations. This is the composition root — the one place that names
    concrete adapters.
    """
    store = GitStore.at(repo, ref=ref, remote=remote)
    return TicketStore(store, clock or SystemClock(), ids or RandomIds())


__all__ = [
    "DEFAULT_TTL",
    "Claim",
    "Committed",
    "Conflict",
    "FakeClock",
    "GitStore",
    "HistoryEntry",
    "Kind",
    "MemStore",
    "Outcome",
    "RandomIds",
    "Refusal",
    "RefusalCode",
    "Refused",
    "RefusedError",
    "RetriesExhausted",
    "Revision",
    "SequentialIds",
    "Stage",
    "Status",
    "Store",
    "StoreError",
    "SystemClock",
    "Ticket",
    "TicketStore",
    "TktError",
    "Unchanged",
    "open_store",
    "raise_for_refusal",
]

__version__ = "0.0.0"
