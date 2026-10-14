"""The clock the application depends on.

A port: the application needs to know the time, but must not read it. The
concrete implementations (system time, a fake for tests) live in
`infrastructure.clock` and are injected at the composition root.
"""

from __future__ import annotations

from typing import Protocol

from tkt_store.domain.ticket import Timestamp


class Clock(Protocol):
    def now(self) -> Timestamp: ...
