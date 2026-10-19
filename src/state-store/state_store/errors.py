"""What can go wrong, as the caller needs to tell it apart (state-store README, *Errors*).

A caller starts again from a new snapshot on `CompareAndSwapFailed` or
`UnknownOutcome`, and stops on `StoreError` or `ValueError`.
"""

from __future__ import annotations


class CompareAndSwapFailed(Exception):
    """The branch was not at the snapshot's revision: another writer committed first.
    Nothing was published."""


class UnknownOutcome(Exception):
    """The commit's outcome could not be read: it may have landed. The next snapshot
    shows whether it did."""


class StoreError(Exception):
    """Anything else (corrupt state, a refused commit, git failing, no such branch); the
    message says which. An operator acts."""
