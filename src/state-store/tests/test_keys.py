"""The key grammar and size limits (state-store README, *Keys*): pure, no git."""

from __future__ import annotations

import pytest

from state_store.keys import (
    MAX_KEY_LENGTH,
    MAX_SEGMENT_LENGTH,
    MAX_VALUE_SIZE,
    check_key,
    check_namespace,
    check_value,
    is_segment,
)

pytestmark = pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="skeleton")

LONGEST_KEY = "/".join(["a" * 100] * 10) + "/" + "a" * 14

VALID_KEYS = [
    "a",
    "inbox/item-1234",
    "store.json",
    "archive/2026/item-0001.json",
    "_private",
    "A/B_c.d-e",
    "x" * MAX_SEGMENT_LENGTH,
    LONGEST_KEY,
]

INVALID_KEYS = [
    "",
    "/",
    "a/",
    "/a",
    "a//b",
    ".",
    "..",
    "a/../b",
    ".git",
    "a/.git/b",
    ".hidden",
    "-option",
    "a/-b",
    "a b",
    "a\\b",
    "a:b",
    "a\nb",
    "a\x00b",
    "é",
    "x" * (MAX_SEGMENT_LENGTH + 1),
    LONGEST_KEY + "a",
]


@pytest.mark.parametrize("key", VALID_KEYS)
def test_valid_keys(key: str) -> None:
    assert check_key(key) == tuple(key.split("/"))


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_invalid_keys(key: str) -> None:
    with pytest.raises(ValueError):
        check_key(key)


def test_a_key_of_exactly_the_limit_is_valid() -> None:
    assert len(LONGEST_KEY) == MAX_KEY_LENGTH
    assert check_key(LONGEST_KEY)


def test_a_key_must_be_a_str() -> None:
    with pytest.raises(ValueError):
        check_key(b"a")  # type: ignore[arg-type]


def test_the_root_namespace_has_no_segments() -> None:
    assert check_namespace("") == ()


@pytest.mark.parametrize("namespace", ["inbox", "archive/2026"])
def test_a_namespace_is_a_key(namespace: str) -> None:
    assert check_namespace(namespace) == tuple(namespace.split("/"))


@pytest.mark.parametrize("namespace", ["/", "inbox/", "/inbox", ".git", "a//b"])
def test_invalid_namespaces(namespace: str) -> None:
    with pytest.raises(ValueError):
        check_namespace(namespace)


@pytest.mark.parametrize("name", ["a", "item-1.json", "_x", "9"])
def test_segments(name: str) -> None:
    assert is_segment(name)


@pytest.mark.parametrize("name", ["", ".", "..", ".git", "-x", "a/b", "a b", "é"])
def test_not_segments(name: str) -> None:
    assert not is_segment(name)


def test_values_up_to_the_limit() -> None:
    assert check_value(b"") == b""
    assert check_value(b"x" * MAX_VALUE_SIZE) == b"x" * MAX_VALUE_SIZE


@pytest.mark.parametrize("value", [b"x" * (MAX_VALUE_SIZE + 1), "text", bytearray(b"x"), None])
def test_values_refused(value: object) -> None:
    with pytest.raises(ValueError):
        check_value(value)  # type: ignore[arg-type]
