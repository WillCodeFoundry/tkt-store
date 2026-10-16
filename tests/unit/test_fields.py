"""The field rules (domain/fields.py): what each value may hold, at the boundaries.

The security suite (tests/security/test_input_validation.py) covers what must be
refused; these tests pin what must stay accepted and where each limit falls."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tkt_store.domain import fields
from tkt_store.domain.ticket import ProjectId, Ticket, TicketId

ACCEPTED_TEXT = {
    "plain": "Fix tests",
    "non-Latin": "Caf\u00e9 \u65e5\u672c \u2713",
    "at the limit": "a" * fields.TITLE_MAX,
    "shell characters": "quotes ' \" and $(not a shell)",
    "decomposed (never normalised)": "Cafe\u0301",
    "emoji with variation selector": "ship it \u2705\ufe0f \U0001f680",
    "text presentation selector": "\u2764\ufe0e",
    "no-break space inside": "a\u00a0b",
    "unassigned today (allowed: the rule never depends on Unicode data)": "x \U0002fffd y",
}


@pytest.mark.parametrize("title", ACCEPTED_TEXT.values(), ids=ACCEPTED_TEXT)
def test_titles_accepted(title: str) -> None:
    assert fields.title_problem(title) is None


TITLES_REFUSED = {
    "empty": "",
    "leading space": " leading",
    "trailing space": "trailing ",
    "too long": "a" * (fields.TITLE_MAX + 1),
    "newline": "two\nlines",
    "tab": "tab\there",
    "private use": "private \ue000 use",
    "private use plane 16": "private \U00100000 use",
    "noncharacter": "non \ufdd0 char",
    "plane noncharacter": "non \U0001fffe char",
    "soft hyphen": "in\u00advisible",
    "variation selector supplement": "a\U000e0101b",
    "variation selectors 1-14": "a\ufe00\ufe01\ufe02",
    "mongolian variation selector": "a\u180bb",
    "braille blank": "a\u2800b",
    "shorthand format control": "a\U0001bca0b",
    "zero-width non-joiner": "a\u200cb",
}


@pytest.mark.parametrize("title", TITLES_REFUSED.values(), ids=TITLES_REFUSED)
def test_titles_refused(title: str) -> None:
    assert fields.title_problem(title) is not None


def test_body_may_be_empty_and_hold_newlines_tabs_and_outer_whitespace() -> None:
    assert fields.body_problem("") is None
    assert fields.body_problem("Steps:\n\t1. run\n\t2. check") is None
    assert fields.body_problem("    indented code\nends with a newline\n") is None
    assert fields.body_problem("b" * fields.BODY_MAX) is None


BODIES_REFUSED = {
    "too long": "b" * (fields.BODY_MAX + 1),
    "line separator": "a\u2028b",
    "carriage return": "cr\rlf",
    "other C0 control": "bell\u0007",
    "zero-width joiner": "a\u200db",
}


@pytest.mark.parametrize("body", BODIES_REFUSED.values(), ids=BODIES_REFUSED)
def test_bodies_refused(body: str) -> None:
    assert fields.body_problem(body) is not None


def test_reason_is_single_line_and_bounded() -> None:
    assert fields.reason_problem("") is None
    assert fields.reason_problem("r" * fields.REASON_MAX) is None
    assert fields.reason_problem("r" * (fields.REASON_MAX + 1)) is not None
    assert fields.reason_problem("a\nb") is not None


@pytest.mark.parametrize("agent", ["coder-7", "a", "a1-b2-c3", "x" * fields.AGENT_MAX])
def test_agents_accepted(agent: str) -> None:
    assert fields.agent_problem(agent) is None


@pytest.mark.parametrize(
    "agent",
    [
        "",
        "A",
        "Coder-7",
        "-a",
        "a-",
        "a--b",
        "a_b",
        "a.b",
        "a b",
        "\u00e9",
        "x" * (fields.AGENT_MAX + 1),
    ],
)
def test_agents_refused(agent: str) -> None:
    assert fields.agent_problem(agent) is not None


def test_tags() -> None:
    assert fields.tags_problem(("auth", "auth")) is not None
    assert fields.tags_problem(()) is None
    assert fields.tags_problem(("auth", "0day", "a-b", "t" * fields.TAG_MAX)) is None
    assert fields.tags_problem(tuple(f"t{n}" for n in range(fields.TAGS_MAX))) is None
    assert fields.tags_problem(tuple(f"t{n}" for n in range(fields.TAGS_MAX + 1))) is not None


@pytest.mark.parametrize(
    "tag", ["", "Auth", "-a", "a-", "a--b", "a_b", "a b", "t" * (fields.TAG_MAX + 1)]
)
def test_tags_refused(tag: str) -> None:
    assert fields.tags_problem((tag,)) is not None


OWNER = "o" * fields.OWNER_MAX
REPO = "r" * fields.REPO_MAX


@pytest.mark.parametrize(
    "project",
    ["tkt-store", "willcodefoundry/tkt-store", "a.b_c-d", "x/a..b", "9" * 40, f"{OWNER}/{REPO}"],
)
def test_projects_accepted(project: str) -> None:
    assert fields.project_problem(project) is None


PROJECTS_REFUSED = {
    "empty": "",
    "no owner": "/repo",
    "no repo": "owner/",
    "three parts": "a/b/c",
    "a URL path": "github.com/org/repo",
    "space": "a b",
    "uppercase": "WillCodeFoundry/tkt-store",
    "dot dot": "..",
    "dot git": ".git",
    "an option": "-x",
    "trailing hyphen": "x-",
    "owner with a dot": "a.b/c",
    "owner too long": f"{OWNER}o/repo",
    "repo too long": f"owner/{REPO}r",
}


@pytest.mark.parametrize("project", PROJECTS_REFUSED.values(), ids=PROJECTS_REFUSED)
def test_projects_refused(project: str) -> None:
    assert fields.project_problem(project) is not None


def test_priority_range() -> None:
    assert fields.priority_problem(fields.PRIORITY_MIN) is None
    assert fields.priority_problem(fields.PRIORITY_MAX) is None
    assert fields.priority_problem(fields.PRIORITY_MIN - 1) is not None
    assert fields.priority_problem(fields.PRIORITY_MAX + 1) is not None


def test_blockers() -> None:
    blockers = tuple(f"tkt-{n:04x}" for n in range(fields.BLOCKERS_MAX + 1))
    assert fields.blockers_problem(blockers[:-1]) is None
    assert fields.blockers_problem(blockers) is not None
    assert fields.blockers_problem(("tkt-0001", "tkt-0001")) is not None
    assert fields.blockers_problem(("tkt-0001", "tkt-x")) == "blocker 2 is not a ticket id"


@pytest.mark.parametrize(
    "ticket_id", ["tkt-7f3a91c2", "tkt-1234", "fix-login-redirect", "0" * 32, "a1b2c3d4"]
)
def test_ticket_ids_accepted(ticket_id: str) -> None:
    assert fields.ticket_id_problem(ticket_id) is None


TICKET_IDS_REFUSED = {
    "7 characters": "abc1234",
    "33 characters": "a" * 33,
    "uppercase": "TKT-1234",
    "leading hyphen": "-tkt1234",
    "trailing hyphen": "tkt-1234-",
    "double hyphen": "tkt--1234",
    "underscore": "tkt_1234",
    "dot": "tkt.1234",
    "slash": "tkt/1234",
    "trailing newline": "tkt-1234\n",
}


@pytest.mark.parametrize("ticket_id", TICKET_IDS_REFUSED.values(), ids=TICKET_IDS_REFUSED)
def test_ticket_ids_refused(ticket_id: str) -> None:
    assert fields.ticket_id_problem(ticket_id) is not None


def test_claim_ids() -> None:
    assert fields.claim_id_problem("c" * 32) is None
    assert fields.claim_id_problem("C" * 32) is not None


def test_absent_optional_values_pass() -> None:
    assert fields.project_problem(None) is None
    assert fields.priority_problem(None) is None
    assert fields.agent_problem(None) is None


def test_presentation_selectors_one_at_a_time() -> None:
    assert fields.title_problem("ok \u2764\ufe0f") is None
    assert fields.title_problem("ok \u2764\ufe0f\ufe0f") is not None
    assert fields.title_problem("ok \ufe0e\ufe0f") is not None


@pytest.mark.parametrize("space", ["\u00a0", "\u2003", "\u3000", "\u1680"])
def test_unicode_whitespace_at_either_end_of_a_title_is_refused(space: str) -> None:
    assert fields.title_problem(f"{space}title") is not None
    assert fields.title_problem(f"title{space}") is not None
    assert fields.title_problem(f"ti{space}tle") is None


@pytest.mark.parametrize("code_point", [0xE0080, 0xE01F0, 0xE0FFF, 0xFFF0, 0xFFF8])
def test_unassigned_invisible_ranges_are_refused(code_point: int) -> None:
    assert fields.title_problem(f"a{chr(code_point)}b") is not None


def test_ticket_problem_checks_every_stored_field() -> None:
    ticket = Ticket(id=TicketId("tkt-0001"), title="Fix it", created=0, updated=0)
    assert fields.ticket_problem(ticket) is None
    broken = {
        "title": replace(ticket, title=" Fix it"),
        "body": replace(ticket, body="a\u202eb"),
        "project": replace(ticket, project=ProjectId("A/B")),
        "priority": replace(ticket, priority=101),
        "self block": replace(ticket, blocked_by=(ticket.id,)),
        "tags": replace(ticket, tags=("Auth",)),
        "content version": replace(ticket, content_version=0),
        "updated before created": replace(ticket, created=5, updated=4),
    }
    for name, value in broken.items():
        assert fields.ticket_problem(value) is not None, name


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
