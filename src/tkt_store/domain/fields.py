"""The field rules: what each stored value may contain (ADR 0005, docs/format.md).

PURE module. One set of checks for every value written to a ticket or a commit
trailer: the rules apply them to ops (`rules.validate_op`) and to every ticket an op
writes (`ticket_problem`), and reading the store will apply them to what it reads.
Each check returns a problem (a short message naming the field, and the position in a
list, never echoing the value) or None; None also stands for an absent optional value
(no project, no priority, no agent).

Identifiers are lowercase *slugs*: letters and digits in runs joined by single hyphens,
never a hyphen at either end. A ticket id is a slug of 8 to 32, a tag a slug of at most
50 (a valid GitHub topic), an agent a slug of at most 39 (a lowercase GitHub username),
and a project is `[owner/]repo` with a slug owner and a repo name that may also hold
'.' and '_'.

Free text (title, body, reason) must be Unicode Assignables (RFC 9839: no controls but
newline and tab, no surrogates, no noncharacters) without private-use characters or a
fixed list of invisible, reordering, line-breaking and hidden-data characters, so
nothing can hide text from a reader, drive a terminal or forge a trailer line. Every
refused character, and the whitespace trimmed from single-line text, is a fixed code
point, so the rule never depends on the Python version or its Unicode data; nothing is
normalised, and comparisons are exact. Lengths count code points.
"""

from __future__ import annotations

import re

from tkt_store.domain.ticket import CLAIM_ID_RE, TICKET_ID_RE, Ticket

TICKET_FILE_MAX = 256 * 1024
"""Bytes in an encoded ticket file: tkt never writes a larger one, and will refuse to
read one."""
CONTENT_FILE_MAX = 192 * 1024
"""Bytes `add` and `edit` may leave in the file. The rest is for the claim history, so
content never stops a ticket being claimed, released, finished or cancelled."""
CLAIM_FILE_MAX = TICKET_FILE_MAX - 1024
"""Bytes a claim may grow the file to. Past it the ticket is full (`FULL`); the last
KiB is for the ops that end a claim (release, done, cancel, reap), so a full ticket
can still be finished or cancelled."""

TITLE_MAX = 256
BODY_MAX = 65_536
REASON_MAX = 256
AGENT_MAX = 39
TAG_MAX = 50
TAGS_MAX = 20
OWNER_MAX = 39
REPO_MAX = 100
BLOCKERS_MAX = 20
PRIORITY_MIN = 0
PRIORITY_MAX = 100

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SLUG_RE = re.compile(_SLUG)
"""Lowercase letters and digits in runs joined by single hyphens."""
REPO_RE = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
"""A repository name: lowercase letters, digits, '.', '_' and '-', starting and ending
with a letter or digit (so never '..', '.git' or an option like '-x')."""


def _cps(*ranges: tuple[int, int]) -> str:
    return "".join(f"{re.escape(chr(lo))}-{re.escape(chr(hi))}" for lo, hi in ranges)


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
    (0x200B, 0x200F),  # zero-width space, non-joiner, joiner; left/right-to-left marks
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
    (0xFFF0, 0xFFFB),  # unassigned specials, interlinear annotation controls: invisible
    (0x13430, 0x1343F),  # egyptian hieroglyph format controls
    (0x1BCA0, 0x1BCA3),  # shorthand format controls: invisible
    (0x1D173, 0x1D17A),  # musical symbol formatting controls
    (0xE0000, 0xE0FFF),  # tags, variation selectors supplement, the rest of the block:
    #                      invisible to people, read by LLMs, can smuggle hidden data
    (0xF0000, 0x10FFFF),  # private use planes 15 and 16
    *((plane + 0xFFFE, plane + 0xFFFF) for plane in range(0, 0xF0000, 0x10000)),
)
"""Code points free text never holds, besides C0 controls. Fixed ranges only: they never
change with the Unicode version. Visible spaces, emoji and the text and emoji
presentation selectors U+FE0E and U+FE0F stay allowed (one at a time); zero-width
joiners (U+200C, U+200D) and tag characters do not, which rules out some Persian and
Indic spellings, joined emoji sequences and subdivision flags."""

_REFUSED = re.compile(f"[{_cps(_C0, *_REFUSED_BEYOND_C0)}]")
_REFUSED_IN_BODY = re.compile(f"[{_cps(*_C0_BUT_NEWLINE_AND_TAB, *_REFUSED_BEYOND_C0)}]")
_SELECTOR_RUN = re.compile(f"[{_cps((0xFE0E, 0xFE0F))}]{{2}}")
"""Two presentation selectors in a row: they mean nothing, and runs of them could carry
hidden data one bit per character."""

_WHITESPACE = "".join(
    chr(c)
    for c in (0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B),
              0x2028, 0x2029, 0x202F, 0x205F, 0x3000)
)  # fmt: skip
"""The whitespace single-line text may not start or end with: a fixed set (the Unicode
White_Space characters), not Python's `str.isspace`, which follows its Unicode data."""


def text_problem(field: str, value: str, *, max_len: int, multiline: bool = False) -> str | None:
    """Free text: at most `max_len` code points and no refused code point (newline and
    tab allowed when `multiline`). Single-line text must not start or end with
    whitespace; a body may (indented code, a trailing newline)."""
    if len(value) > max_len:
        return f"{field} is longer than {max_len} characters"
    if found := (_REFUSED_IN_BODY if multiline else _REFUSED).search(value):
        return f"{field} contains U+{ord(found[0]):04X}, a control or invisible character"
    if _SELECTOR_RUN.search(value):
        return f"{field} contains two variation selectors in a row"
    if not multiline and value != value.strip(_WHITESPACE):
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
    if agent is not None and (len(agent) > AGENT_MAX or not SLUG_RE.fullmatch(agent)):
        return (
            f"agent must be 1 to {AGENT_MAX} lowercase letters, digits and single hyphens, "
            f"starting and ending with a letter or digit"
        )
    return None


def tags_problem(tags: tuple[str, ...]) -> str | None:
    if len(tags) > TAGS_MAX:
        return f"at most {TAGS_MAX} tags"
    for position, tag in enumerate(tags, 1):
        if len(tag) > TAG_MAX or not SLUG_RE.fullmatch(tag):
            return (
                f"tag {position} must be 1 to {TAG_MAX} lowercase letters, digits and "
                f"single hyphens, starting and ending with a letter or digit"
            )
    if len(set(tags)) != len(tags):
        return "tags list a tag twice"
    return None


def project_problem(project: str | None) -> str | None:
    if project is None:
        return None
    owner, slash, repo = project.rpartition("/")
    owner_ok = not slash or (len(owner) <= OWNER_MAX and SLUG_RE.fullmatch(owner))
    if not owner_ok or len(repo) > REPO_MAX or not REPO_RE.fullmatch(repo):
        return (
            f"project must be [owner/]repo: an owner of 1 to {OWNER_MAX} lowercase letters, "
            f"digits and single hyphens, and a repo of 1 to {REPO_MAX} lowercase letters, "
            f"digits, '.', '_' and '-', starting and ending with a letter or digit"
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


def ticket_problem(ticket: Ticket) -> str | None:
    """The first field of a whole ticket that breaks its rule, or None: every stored
    value, including a ticket blocking itself and the claim history. Run on every ticket
    an op writes, so tkt never writes an invalid ticket, and to be run on every ticket
    read."""
    claim = ticket.claim
    verdicts = (
        ticket_id_problem(ticket.id),
        title_problem(ticket.title),
        body_problem(ticket.body),
        project_problem(ticket.project),
        priority_problem(ticket.priority),
        blockers_problem(ticket.blocked_by),
        "a ticket cannot block itself" if ticket.id in ticket.blocked_by else None,
        tags_problem(ticket.tags),
        None if claim is None else agent_problem(claim.agent),
        None if claim is None else claim_id_problem(claim.claim_id),
        *(
            f"ended claim {position} is not a claim id"
            for position, claim_id in enumerate(ticket.ended_claim_ids, 1)
            if claim_id_problem(claim_id)
        ),
    )
    return next((verdict for verdict in verdicts if verdict is not None), None)
