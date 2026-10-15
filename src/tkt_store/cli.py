"""`tkt` command line (docs/cli.md).

Thin interface adapter: it parses arguments, builds a TicketStore through the
composition root, renders the Outcome, and maps it to an exit code. It holds no
rules; everything it shows comes from the application layer.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from enum import IntEnum

from tkt_store import open_store  # noqa: F401  (composition root, used by run())


class ExitCode(IntEnum):
    OK = 0
    REFUSED = 1
    USAGE = 2
    RETRIES_EXHAUSTED = 3
    STORE_ERROR = 4


COMMANDS = (
    "init",
    "add",
    "update",
    "list",
    "show",
    "claim",
    "claim-next",
    "renew",
    "release",
    "done",
    "cancel",
    "reap",
    "log",
)


def build_parser() -> argparse.ArgumentParser:
    """Global options (--repo, --ref, --remote/--no-remote, --json) and one subparser
    per command."""
    parser = argparse.ArgumentParser(
        prog="tkt", description="Ticket store for coordinating agents."
    )
    parser.add_argument(
        "--repo", help="store repository (default: $TKT_REPO; usage error if neither is set)"
    )
    parser.add_argument("--ref", help="store ref (default: refs/heads/tkt)")
    remote = parser.add_mutually_exclusive_group()
    remote.add_argument(
        "--remote", default="origin", help="shared remote; must be configured (default: origin)"
    )
    remote.add_argument(
        "--no-remote",
        dest="remote",
        action="store_const",
        const=None,
        help="use a local-only store",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        sub.add_parser(name)  # options per command: see docs/cli.md (not yet wired)
    return parser


def run(args: argparse.Namespace) -> int:
    """Build a TicketStore (via tkt_store.open_store), render the Outcome, return an ExitCode."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except NotImplementedError:
        parser.exit(ExitCode.STORE_ERROR, "tkt: not implemented yet (skeleton)\n")
