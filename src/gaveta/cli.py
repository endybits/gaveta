"""Console entry point — simulated capture.

Stage 1 saves nothing. It resolves the input, builds a `CaptureRequest`, and prints
what *would* be saved. The parsing seam (argparse plus an explicit reserved-word
check, rather than a CLI framework) is recorded in ADR-001.
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime

from gaveta import __version__
from gaveta.commands import reserved_head, reserved_message
from gaveta.models import CaptureRequest
from gaveta.render import render_human, render_json

_STDIN_TOKEN = "-"

_DESCRIPTION = (
    "Capture text into your drawer. Stage 1 simulates saving: nothing is stored yet."
)

_EPILOG = (
    'Text starting with a dash must follow `--`, e.g.  gaveta -- "ssh -L 5432:host"\n'
    "Reserved command names (ls, show, rm, f, ...) are not implemented yet."
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
        help="emit one JSON object instead of the human view",
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
    """Run the CLI. Returns the exit code: 0 on capture, 2 on nothing to capture."""
    tokens = list(sys.argv[1:] if argv is None else argv)

    # Checked before argparse, which would otherwise swallow a reserved word as a
    # positional. Only the first token is inspected, so `gaveta ls links` is a
    # reserved command while `gaveta "ls my files"` is ordinary text.
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

    request = CaptureRequest(raw=raw, captured_at=datetime.now().astimezone())
    view = render_json(request) if args.json_out else render_human(request)
    sys.stdout.write(view if view.endswith("\n") else view + "\n")
    return 0
