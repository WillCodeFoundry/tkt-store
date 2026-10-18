"""The key grammar and size limits (state-store.md, *Keys*). Pure: no git, no IO.

A key is one or more segments joined by `/`. A segment is 1 to `MAX_SEGMENT_LENGTH`
characters from `A-Z a-z 0-9 . _ -` and starts with a letter, digit or `_`. A key is at
most `MAX_KEY_LENGTH` characters. A namespace is `""` (the root) or a valid key.
"""

from __future__ import annotations

MAX_VALUE_SIZE = 1024 * 1024
"""Bytes in a value. Larger values are refused on writing and are corrupt on reading."""

MAX_KEY_LENGTH = 1024
MAX_SEGMENT_LENGTH = 128


def check_key(key: str) -> tuple[str, ...]:
    """The segments of `key`; `ValueError` if it is not a valid key."""
    raise NotImplementedError


def check_namespace(namespace: str) -> tuple[str, ...]:
    """The segments of `namespace` (none for the root); `ValueError` if invalid."""
    raise NotImplementedError


def is_segment(name: str) -> bool:
    """Whether `name` is a valid segment: what every entry name read from git must be."""
    raise NotImplementedError


def check_value(value: bytes) -> bytes:
    """`value` itself; `ValueError` if it is not bytes or is over `MAX_VALUE_SIZE`."""
    raise NotImplementedError
