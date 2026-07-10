"""Console entry point.

Capture resolves the input, hands it to `gaveta.core`, and prints the item that was
saved. The CLI is a client of the core, not the other way round: nothing here decides
what a capture *is*, only how it is spelled and how it is shown.

The parsing seam (argparse plus an explicit reserved-word check, rather than a CLI
framework) is recorded in ADR-001.
"""

import argparse
import sys
from collections.abc import Callable

from gaveta import __version__, core
from gaveta.commands import implemented_head, reserved_head, reserved_message
from gaveta.db.session import session as db_session
from gaveta.render import render_json, render_saved
from gaveta.subcommands import DISPATCH

_STDIN_TOKEN = "-"

_DESCRIPTION = "Capture text into your drawer, or manage what you have captured."

_EPILOG = (
    "Commands:  ls [type] · show <id> · rm <id> · export\n"
    "A bare dash token (-L) is read as an option; put it after `--` to capture it,\n"
    'e.g.  gaveta -- "-L". Quoted text containing a space ("ssh -L 5432") is fine.\n'
    "Reserved for later stages: retag, f, reindex, cred, daemon, ui."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaveta",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "text",
        nargs="*",
        help=f"text to capture; use {_STDIN_TOKEN!r} to read it from stdin",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="emit the saved item as one JSON object instead of the confirmation",
    )
    parser.add_argument("--version", action="version", version=f"gaveta {__version__}")
    return parser


def _resolve_raw(
    tokens: list[str],
    read_stdin: Callable[[], str],
    stdin_isatty: bool,
) -> str | None:
    """Resolve the text to capture, or None when there is nothing to capture.

    stdin is read lazily: `read_stdin` is called only on the branches that need it.
    Reading it eagerly to decide the source makes `gaveta "text"` hang whenever
    stdin is an open pipe.

    Empty or whitespace-only input means *nothing to capture*, whether it arrived
    over a pipe or from a tty. That equivalence is what makes `gaveta` behave the
    same on a developer's terminal and on a CI runner, where stdin is never a tty.
    """
    if tokens == [_STDIN_TOKEN]:
        return read_stdin().strip() or None
    if tokens:
        return " ".join(tokens).strip() or None
    if not stdin_isatty:
        return read_stdin().strip() or None
    return None


def main(argv: list[str] | None = None) -> int:
    """Run the CLI, and return its exit code.

    Dispatch order, all keyed on the first token only (so `gaveta "ls my files"` stays
    text):

    1. An implemented subcommand (`ls`/`show`/`rm`/`export`) → its handler.
    2. A still-reserved word (`f`, `cred`, …) → usage, exit 2.
    3. Anything else → capture.
    """
    tokens = list(sys.argv[1:] if argv is None else argv)

    # Subcommands and reserved words are both checked before argparse, which would
    # otherwise swallow the leading token as capture text.
    implemented = implemented_head(tokens)
    if implemented is not None:
        return DISPATCH[implemented](tokens[1:])

    reserved = reserved_head(tokens)
    if reserved is not None:
        print(reserved_message(reserved), file=sys.stderr)
        return 2

    parser = _build_parser()
    args = parser.parse_args(tokens)

    raw = _resolve_raw(args.text, sys.stdin.read, sys.stdin.isatty())
    if raw is None:
        parser.print_usage(sys.stderr)
        print("\n[gaveta] nothing to capture.", file=sys.stderr)
        return 2

    with db_session() as session:
        saved = core.capture(raw, session=session)

    view = render_json(saved) if args.json_out else render_saved(saved)
    sys.stdout.write(view if view.endswith("\n") else view + "\n")
    return 0
