"""The implemented subcommands: ls, show, rm, export.

Each is a thin client of `gaveta.core` — it parses its own tiny argument surface, calls
one or two core functions, and renders. No business logic lives here; the core is the
product (ADR-001, and the daemon in Stage 7 depends on it staying that way).

Each handler returns an exit code. The dispatch table at the bottom is what `cli.py`
consults after the reserved-word check.
"""

import argparse
import sys
from collections.abc import Callable

from gaveta import core
from gaveta.db.models import ItemType
from gaveta.db.session import session as db_session
from gaveta.exit_codes import ExitCode
from gaveta.render import (
    render_item,
    render_json,
    render_json_list,
    render_list,
    render_removed,
)

# A handler takes the tokens *after* the subcommand name and returns an exit code.
Handler = Callable[[list[str]], int]


def _emit(text: str) -> None:
    """Write a rendered view, ensuring exactly one trailing newline."""
    if text:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _ls(args: list[str]) -> int:
    """`gaveta ls [type]` — recent captures first, optionally filtered by type."""
    parser = argparse.ArgumentParser(prog="gaveta ls", add_help=True)
    parser.add_argument(
        "type",
        nargs="?",
        help="only this type: link, command, note, credential_ref, unknown",
    )
    parser.add_argument("--json", action="store_true", dest="json_out")
    parsed = parser.parse_args(args)

    item_type: ItemType | None = None
    if parsed.type is not None:
        try:
            item_type = ItemType(parsed.type)
        except ValueError:
            valid = ", ".join(t.value for t in ItemType)
            print(
                f"[gaveta] ✗ unknown type '{parsed.type}'. Valid types: {valid}",
                file=sys.stderr,
            )
            return ExitCode.USAGE

    with db_session() as session:
        items = core.list_items(item_type, session=session)

    _emit(render_json_list(items) if parsed.json_out else render_list(items))
    return ExitCode.OK


def _show(args: list[str]) -> int:
    """`gaveta show <id>` — one capture in full, or exit 1 if there is no such id."""
    parser = argparse.ArgumentParser(prog="gaveta show", add_help=True)
    parser.add_argument("id", type=int, help="the id from `gaveta ls`")
    parser.add_argument("--json", action="store_true", dest="json_out")
    parsed = parser.parse_args(args)

    with db_session() as session:
        item = core.get_item(parsed.id, session=session)

    if item is None:
        print(f"[gaveta] ✗ no item with id {parsed.id}", file=sys.stderr)
        return ExitCode.NOT_FOUND

    _emit(render_json(item) if parsed.json_out else render_item(item))
    return ExitCode.OK


def _rm(args: list[str]) -> int:
    """`gaveta rm <id>` — idempotent delete. Exit 0 whether or not the id was there."""
    parser = argparse.ArgumentParser(prog="gaveta rm", add_help=True)
    parser.add_argument("id", type=int, help="the id from `gaveta ls`")
    parsed = parser.parse_args(args)

    with db_session() as session:
        existed = core.delete_item(parsed.id, session=session)

    _emit(render_removed(parsed.id, existed))
    return ExitCode.OK


def _export(args: list[str]) -> int:
    """`gaveta export` — the whole drawer as a JSON array on stdout.

    Redirection is the file story: `gaveta export > backup.json`. No `--output` flag; it
    would be a second, worse implementation of `>`.
    """
    argparse.ArgumentParser(prog="gaveta export", add_help=True).parse_args(args)

    with db_session() as session:
        items = core.export_items(session=session)

    _emit(render_json_list(items))
    return ExitCode.OK


DISPATCH: dict[str, Handler] = {
    "ls": _ls,
    "show": _show,
    "rm": _rm,
    "export": _export,
}
