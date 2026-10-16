"""The field rules (domain/fields.py): what each value may hold, at the boundaries.

The security suite (tests/security/test_input_validation.py) covers what must be
refused; these tests pin what must stay accepted and where each limit falls."""

from __future__ import annotations

import pytest

from tkt_store.domain import fields

ACCEPTED_TEXT = [
    "Fix tests",
    "Caf\u00e9 \u65e5\u672c \u2713",
    "a" * fields.TITLE_MAX,
    "quotes ' \" and $(not a shell)",
]


@pytest.mark.parametrize("title", ACCEPTED_TEXT)
def test_titles_accepted(title: str) -> None:
    assert fields.title_problem(title) is None


TITLES_REFUSED = {
    "empty": "",
    "leading space": " leading",
    "trailing space": "trailing ",
    "too long": "a" * (fields.TITLE_MAX + 1),
    "newline": "two\nlines",
    "tab": "tab\there",
    "NFD (e + combining acute)": "Cafe\u0301",
    "private use": "private \ue000 use",
    "unassigned": "unassigned \U000e0080",
}


@pytest.mark.parametrize("title", TITLES_REFUSED.values(), ids=TITLES_REFUSED)
def test_titles_refused(title: str) -> None:
    assert fields.title_problem(title) is not None


def test_body_may_be_empty_and_hold_newlines_and_tabs() -> None:
    assert fields.body_problem("") is None
    assert fields.body_problem("Steps:\n\t1. run\n\t2. check") is None
    assert fields.body_problem("b" * fields.BODY_MAX) is None


BODIES_REFUSED = {
    "too long": "b" * (fields.BODY_MAX + 1),
    "trailing newline": "ends with a newline\n",
    "line separator": "a\u2028b",
    "carriage return": "cr\rlf",
}


@pytest.mark.parametrize("body", BODIES_REFUSED.values(), ids=BODIES_REFUSED)
def test_bodies_refused(body: str) -> None:
    assert fields.body_problem(body) is not None


def test_reason_is_single_line_and_bounded() -> None:
    assert fields.reason_problem("") is None
    assert fields.reason_problem("r" * fields.REASON_MAX) is None
    assert fields.reason_problem("r" * (fields.REASON_MAX + 1)) is not None
    assert fields.reason_problem("a\nb") is not None


@pytest.mark.parametrize("agent", ["coder-7", "A", "a1-b2-c3", "x" * fields.AGENT_MAX])
def test_agents_accepted(agent: str) -> None:
    assert fields.agent_problem(agent) is None


@pytest.mark.parametrize(
    "agent", ["", "-a", "a-", "a--b", "a_b", "a.b", "a b", "\u00e9", "x" * (fields.AGENT_MAX + 1)]
)
def test_agents_refused(agent: str) -> None:
    assert fields.agent_problem(agent) is not None


def test_tags() -> None:
    assert fields.tags_problem(("auth", "auth")) is not None
    assert fields.tags_problem(()) is None
    assert fields.tags_problem(("auth", "0day", "a-b-", "t" * fields.TAG_MAX)) is None
    assert fields.tags_problem(tuple(f"t{n}" for n in range(fields.TAGS_MAX))) is None
    assert fields.tags_problem(tuple(f"t{n}" for n in range(fields.TAGS_MAX + 1))) is not None


@pytest.mark.parametrize("tag", ["", "Auth", "-a", "a_b", "a b", "t" * (fields.TAG_MAX + 1)])
def test_tags_refused(tag: str) -> None:
    assert fields.tags_problem((tag,)) is not None


SEGMENT = "p" * fields.PROJECT_SEGMENT_MAX


@pytest.mark.parametrize(
    "project",
    ["tkt-store", "WillCodeFoundry/tkt-store", "a.b_c-d", "9" * 40, f"{SEGMENT}/{SEGMENT}"],
)
def test_projects_accepted(project: str) -> None:
    assert fields.project_problem(project) is None


@pytest.mark.parametrize(
    "project", ["", "/repo", "owner/", "a/b/c", "github.com/org/repo", "a b", SEGMENT + "p"]
)
def test_projects_refused(project: str) -> None:
    assert fields.project_problem(project) is not None


def test_priority_range() -> None:
    assert fields.priority_problem(fields.PRIORITY_MIN) is None
    assert fields.priority_problem(fields.PRIORITY_MAX) is None
    assert fields.priority_problem(fields.PRIORITY_MIN - 1) is not None
    assert fields.priority_problem(fields.PRIORITY_MAX + 1) is not None


def test_blockers() -> None:
    blockers = tuple(f"tkt-{n:x}" for n in range(fields.BLOCKERS_MAX + 1))
    assert fields.blockers_problem(blockers[:-1]) is None
    assert fields.blockers_problem(blockers) is not None
    assert fields.blockers_problem(("tkt-1", "tkt-1")) is not None
    assert fields.blockers_problem(("tkt-1", "tkt-x")) == (
        "blocker 2 must be tkt- followed by lowercase hex"
    )


def test_ids() -> None:
    assert fields.ticket_id_problem("tkt-7f3a91c2") is None
    assert fields.ticket_id_problem("tkt-1\n") is not None
    assert fields.claim_id_problem("c" * 32) is None
    assert fields.claim_id_problem("C" * 32) is not None


def test_absent_optional_values_pass() -> None:
    assert fields.project_problem(None) is None
    assert fields.priority_problem(None) is None
    assert fields.agent_problem(None) is None


def test_ticket_file_cap() -> None:
    assert fields.ticket_file_problem(b"x" * fields.TICKET_FILE_MAX) is None
    assert fields.ticket_file_problem(b"x" * (fields.TICKET_FILE_MAX + 1)) is not None


def test_problems_never_echo_the_value() -> None:
    value = "SECRET\u202e"
    for problem in [
        fields.title_problem(value),
        fields.body_problem(value),
        fields.reason_problem(value),
        fields.agent_problem(value),
        fields.tags_problem((value,)),
        fields.project_problem(value),
        fields.ticket_id_problem(value),
        fields.claim_id_problem(value),
        fields.blockers_problem((value,)),
    ]:
        assert problem is not None and "SECRET" not in problem
