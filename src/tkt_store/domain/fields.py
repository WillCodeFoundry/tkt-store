"""The field rules: what each stored value may contain (ADR 0005, docs/format.md).

PURE module. One set of checks for every value written to a ticket or a commit
trailer; the rules apply them to ops (`rules.validate_op`), and reading the store will
apply them to what it reads. Each check returns a problem (a short message naming the
field, and the position in a list, never echoing the value) or None; None also stands
for an absent optional value (no project, no priority, no agent).

Identifiers follow GitHub's rules, since the values usually are GitHub names: a holder
(today the acting agent) is a username, a tag is a topic, a project is `[owner/]repo`.
Free text (title, body, reason) must be Unicode Assignables (RFC 9839: no controls but
newline and tab, no surrogates, no noncharacters) without private-use characters or a
fixed list of invisible, reordering and line-breaking characters, so nothing can hide
text from a reader, drive a terminal or forge a trailer line. Every refused character
sits in a fixed range, so the rule never depends on the Python version or its Unicode
data; nothing is normalised, and comparisons are exact. Lengths count code points.
"""

from __future__ import annotations

import re

from tkt_store.domain.ticket import CLAIM_ID_RE, TICKET_ID_RE

TICKET_FILE_MAX = 256 * 1024
"""Bytes in an encoded ticket file. Writes that would exceed it are refused, so tkt never
writes a file it would refuse to read."""
TITLE_MAX = 256
BODY_MAX = 65_536
REASON_MAX = 256
AGENT_MAX = 39
TAG_MAX = 50
TAGS_MAX = 20
PROJECT_SEGMENT_MAX = 100
BLOCKERS_MAX = 20
PRIORITY_MIN = 0
PRIORITY_MAX = 100

AGENT_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
"""A GitHub username: letters, digits and single hyphens, no hyphen at either end."""

TAG_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
"""A GitHub topic: lowercase letters, digits and hyphens, starting with a letter or digit."""

_SEGMENT = rf"[A-Za-z0-9._-]{{1,{PROJECT_SEGMENT_MAX}}}"
PROJECT_RE = re.compile(rf"(?:{_SEGMENT}/)?{_SEGMENT}")
"""`[owner/]repo`, each segment at most PROJECT_SEGMENT_MAX of `[A-Za-z0-9._-]`."""

_C0 = (0x0000, 0x001F)
"""C0 controls, newline and tab included."""
_C0_BUT_NEWLINE_AND_TAB = ((0x0000, 0x0008), (0x000B, 0x001F))
"""C0 controls a body may not hold: all but tab (U+0009) and newline (U+000A)."""

_REFUSED_BEYOND_C0 = (
    (0x007F, 0x009F),  # DEL and C1 controls (U+0085 is a line break)
    (0x00AD, 0x00AD),  # soft hyphen: invisible
    (0x034F, 0x034F),  # combining grapheme joiner: invisible
    (0x061C, 0x061C),  # arabic letter mark: bidi
    (0x115F, 0x1160),  # hangul fillers: render blank
    (0x17B4, 0x17B5),  # khmer inherent vowels: invisible
    (0x180B, 0x180F),  # mongolian variation selectors and vowel separator: hidden data
    (0x200B, 0x200F),  # zero-width characters, left/right-to-left marks
    (0x2028, 0x202E),  # line and paragraph separators, bidi embeddings and overrides
    (0x2060, 0x206F),  # word joiner, invisible operators, bidi isolates, deprecated formats
    (0x2800, 0x2800),  # braille blank: renders as empty space
    (0x3164, 0x3164),  # hangul filler
    (0xD800, 0xDFFF),  # surrogates
    (0xE000, 0xF8FF),  # private use
    (0xFDD0, 0xFDEF),  # noncharacters
    (0xFE00, 0xFE0D),  # variation selectors 1-14: can smuggle hidden data (FE0E/FE0F allowed)
    (0xFEFF, 0xFEFF),  # zero-width no-break space (byte order mark)
    (0xFFA0, 0xFFA0),  # halfwidth hangul filler
    (0xFFF9, 0xFFFB),  # interlinear annotation controls
    (0x13430, 0x1343F),  # egyptian hieroglyph format controls
    (0x1BCA0, 0x1BCA3),  # shorthand format controls: invisible
    (0x1D173, 0x1D17A),  # musical symbol formatting controls
    (0xE0000, 0xE007F),  # tag characters: invisible to people, read by LLMs
    (0xE0100, 0xE01EF),  # variation selectors supplement: can smuggle hidden data
    (0xF0000, 0x10FFFF),  # private use planes 15 and 16
    *((plane + 0xFFFE, plane + 0xFFFF) for plane in range(0, 0xF0000, 0x10000)),
)
"""Code points free text never holds, besides C0 controls. Fixed ranges only: they never
change with the Unicode version. Visible spaces, emoji and the text and emoji
presentation selectors U+FE0E and U+FE0F stay allowed; zero-width joiners (U+200C, U+200D)
do not, which rules out some Persian and Indic spellings and joined emoji sequences."""


def _class(ranges: tuple[tuple[int, int], ...]) -> re.Pattern[str]:
    return re.compile("[" + "".join(f"\\U{lo:08x}-\\U{hi:08x}" for lo, hi in ranges) + "]")


_REFUSED = _class((_C0, *_REFUSED_BEYOND_C0))
_REFUSED_IN_BODY = _class((*_C0_BUT_NEWLINE_AND_TAB, *_REFUSED_BEYOND_C0))


def text_problem(field: str, value: str, *, max_len: int, multiline: bool = False) -> str | None:
    """Free text: at most `max_len` code points and no refused code point (newline and
    tab allowed when `multiline`). Single-line text must not start or end with
    whitespace; a body may (indented code, a trailing newline)."""
    if len(value) > max_len:
        return f"{field} is longer than {max_len} characters"
    if found := (_REFUSED_IN_BODY if multiline else _REFUSED).search(value):
        return f"{field} contains U+{ord(found[0]):04X}, a control or invisible character"
    if not multiline and value != value.strip():
        return f"{field} has leading or trailing whitespace"
    return None


def title_problem(title: str) -> str | None:
    if not title:
        return "title must not be empty"
    return text_problem("title", title, max_len=TITLE_MAX)


def body_problem(body: str) -> str | None:
    return text_problem("body", body, max_len=BODY_MAX, multiline=True)


def reason_problem(reason: str) -> str | None:
    return text_problem("reason", reason, max_len=REASON_MAX)


def ticket_id_problem(ticket_id: str) -> str | None:
    if not TICKET_ID_RE.fullmatch(ticket_id):
        return (
            "ticket id must be 8 to 32 lowercase letters, digits and single hyphens, "
            "starting and ending with a letter or digit"
        )
    return None


def claim_id_problem(claim_id: str) -> str | None:
    if not CLAIM_ID_RE.fullmatch(claim_id):
        return "claim id must be 32 lowercase hex characters"
    return None


def agent_problem(agent: str | None) -> str | None:
    if agent is None:
        return None
    if len(agent) > AGENT_MAX or not AGENT_RE.fullmatch(agent):
        return (
            f"agent must be a GitHub-style username: letters, digits and single hyphens, "
            f"no hyphen at either end, at most {AGENT_MAX}"
        )
    return None


def tags_problem(tags: tuple[str, ...]) -> str | None:
    if len(tags) > TAGS_MAX:
        return f"at most {TAGS_MAX} tags"
    for position, tag in enumerate(tags, 1):
        if len(tag) > TAG_MAX or not TAG_RE.fullmatch(tag):
            return (
                f"tag {position} must be lowercase letters, digits and hyphens, starting "
                f"with a letter or digit, at most {TAG_MAX}"
            )
    if len(set(tags)) != len(tags):
        return "tags list a tag twice"
    return None


def project_problem(project: str | None) -> str | None:
    if project is not None and not PROJECT_RE.fullmatch(project):
        return (
            f"project must be [owner/]repo, each part letters, digits, '.', '_' or '-', "
            f"at most {PROJECT_SEGMENT_MAX}"
        )
    return None


def priority_problem(priority: int | None) -> str | None:
    if priority is not None and not PRIORITY_MIN <= priority <= PRIORITY_MAX:
        return f"priority must be between {PRIORITY_MIN} and {PRIORITY_MAX}"
    return None


def blockers_problem(blocked_by: tuple[str, ...]) -> str | None:
    if len(blocked_by) > BLOCKERS_MAX:
        return f"at most {BLOCKERS_MAX} blockers"
    for position, blocker in enumerate(blocked_by, 1):
        if ticket_id_problem(blocker):
            return f"blocker {position} is not a ticket id"
    if len(set(blocked_by)) != len(blocked_by):
        return "blocked_by lists a ticket twice"
    return None


def ticket_file_problem(encoded: bytes) -> str | None:
    if len(encoded) > TICKET_FILE_MAX:
        return f"the ticket file would exceed {TICKET_FILE_MAX // 1024} KiB"
    return None
