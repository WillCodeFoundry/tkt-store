"""The field rules: what each stored value may contain (ADR 0005, docs/format.md).

PURE module. One set of checks for every value written to a ticket or a commit
trailer; the rules apply them to ops (`rules.validate_op`), and reading the store will
apply them to what it reads. Each check returns a problem (a short message naming the
field, never echoing the value) or None.

Identifiers follow GitHub's rules, since the values usually are GitHub names: a holder
(today the acting agent) is a username, a tag is a topic, a project is `[owner/]repo`.
Free text (title, body, reason) follows a PRECIS-style rule (RFC 8264): NFC, and no
control, format, private-use, surrogate or unassigned characters, nor line or
paragraph separators, so nothing can hide text from a reader, drive a terminal or
forge a trailer line. Lengths count code points.
"""

from __future__ import annotations

import re
import unicodedata

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

REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"})
"""Control, format (bidi, zero-width, tag characters), private-use, surrogate and
unassigned characters, and line and paragraph separators."""

BODY_CONTROLS = frozenset("\n\t")
"""The only control characters free text may hold, and only in a body."""


def text_problem(field: str, value: str, *, max_len: int, multiline: bool = False) -> str | None:
    """Free text: NFC, at most `max_len` code points, no refused character (newline and
    tab allowed when `multiline`), no leading or trailing whitespace."""
    if not unicodedata.is_normalized("NFC", value):
        return f"{field} must be in Unicode NFC"
    if len(value) > max_len:
        return f"{field} is longer than {max_len} characters"
    allowed = BODY_CONTROLS if multiline else frozenset()
    for char in value:
        if char not in allowed and unicodedata.category(char) in REFUSED_CATEGORIES:
            return f"{field} contains U+{ord(char):04X}, a control or invisible character"
    if value != value.strip():
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


def agent_problem(agent: str) -> str | None:
    if len(agent) > AGENT_MAX or not AGENT_RE.fullmatch(agent):
        return (
            f"agent must be a GitHub-style username: letters, digits and single hyphens, "
            f"no hyphen at either end, at most {AGENT_MAX}"
        )
    return None


def tags_problem(tags: tuple[str, ...]) -> str | None:
    if len(tags) > TAGS_MAX:
        return f"at most {TAGS_MAX} tags"
    for tag in tags:
        if len(tag) > TAG_MAX or not TAG_RE.fullmatch(tag):
            return (
                f"a tag must be lowercase letters, digits and hyphens, starting with a "
                f"letter or digit, at most {TAG_MAX}"
            )
    return None


def project_problem(project: str) -> str | None:
    if not PROJECT_RE.fullmatch(project):
        return (
            f"project must be [owner/]repo, each part letters, digits, '.', '_' or '-', "
            f"at most {PROJECT_SEGMENT_MAX}"
        )
    return None


def priority_problem(priority: int) -> str | None:
    if not PRIORITY_MIN <= priority <= PRIORITY_MAX:
        return f"priority must be between {PRIORITY_MIN} and {PRIORITY_MAX}"
    return None


def blockers_problem(blocked_by: tuple[str, ...]) -> str | None:
    if len(blocked_by) > BLOCKERS_MAX:
        return f"at most {BLOCKERS_MAX} blockers"
    if len(set(blocked_by)) != len(blocked_by):
        return "blocked_by lists a ticket twice"
    return None
