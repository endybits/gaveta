"""The implemented subcommands: ls, show, rm, export.

Each is a thin client of `gaveta.core` — it parses its own tiny argument surface,
calls one or two core functions, and renders. No business logic lives here; the core
is the product (ADR-001, and the daemon in Stage 7 depends on it staying that way).

Each handler returns an exit code. The dispatch table at the bottom is what `cli.py`
consults after the reserved-word check.
"""

import argparse
import sys
from collections.abc import Callable

from gaveta import core
from gaveta.brain import make_classifier, make_embedder
from gaveta.config import ConfigError, load_config
from gaveta.db.models import ItemType
from gaveta.db.session import session as db_session
from gaveta.db.session import vectors_available
from gaveta.exit_codes import ExitCode
from gaveta.mapping import to_search_hit
from gaveta.render import (
    render_item,
    render_json,
    render_json_list,
    render_list,
    render_reindexed,
    render_removed,
    render_retagged,
    render_search,
    render_search_json,
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


def _retag(args: list[str]) -> int:
    """`gaveta retag <id>` — re-classify a capture, or exit 1 if there is no such id.

    The upgrade path: a capture saved via the heuristic fallback (no Ollama) gets a
    real classification once the model is available. Prints the retagged line — not
    "saved", since nothing new was stored.
    """
    parser = argparse.ArgumentParser(prog="gaveta retag", add_help=True)
    parser.add_argument("id", type=int, help="the id from `gaveta ls`")
    parser.add_argument("--json", action="store_true", dest="json_out")
    parsed = parser.parse_args(args)

    # A broken config.toml is a usage error, before any work — same as the capture
    # path.
    try:
        classifier = make_classifier(load_config())
    except ConfigError as exc:
        print(f"[gaveta] {exc}", file=sys.stderr)
        return ExitCode.USAGE

    with db_session() as session:
        item = core.retag(parsed.id, session=session, classifier=classifier)

    if item is None:
        print(f"[gaveta] ✗ no item with id {parsed.id}", file=sys.stderr)
        return ExitCode.NOT_FOUND

    _emit(render_json(item) if parsed.json_out else render_retagged(item))
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

    Redirection is the file story: `gaveta export > backup.json`. No `--output` flag;
    it would be a second, worse implementation of `>`.
    """
    argparse.ArgumentParser(prog="gaveta export", add_help=True).parse_args(args)

    with db_session() as session:
        items = core.export_items(session=session)

    _emit(render_json_list(items))
    return ExitCode.OK


def _f(args: list[str]) -> int:
    """`gaveta f "query" [--json]` — find items by meaning, best first.

    Runs the FTS5 keyword search always, fused with a vector search where a model and
    the sqlite-vec index are both available. When the vector index cannot load, a
    one-line notice goes to *stderr* (so `f --json` and `f | …` stay clean) and
    retrieval is keyword-only.

    A search that matches nothing is not an error: it prints a "no matches" notice to
    stderr, an empty JSON array under `--json`, and exits 0 — like `ls` on an empty
    drawer, unlike `show <missing>`.
    """
    parser = argparse.ArgumentParser(prog="gaveta f", add_help=True)
    parser.add_argument("query", help="what to look for, by meaning")
    parser.add_argument("--json", action="store_true", dest="json_out")
    parsed = parser.parse_args(args)

    # A broken config.toml is a usage error, before any work — as on the capture path.
    try:
        embedder = make_embedder(load_config())
    except ConfigError as exc:
        print(f"[gaveta] {exc}", file=sys.stderr)
        return ExitCode.USAGE

    with db_session() as session:
        results = core.find(parsed.query, session=session, embedder=embedder)
        # `vectors_available()` is only meaningful after a connection has opened,
        # which the query above guarantees.
        vectors_on = vectors_available()

    if not vectors_on:
        print(
            "[gaveta] keyword search only — vector index unavailable",
            file=sys.stderr,
        )

    hits = [to_search_hit(r) for r in results]
    if not hits:
        print(f"[gaveta] no matches for {parsed.query!r}", file=sys.stderr)

    _emit(render_search_json(hits) if parsed.json_out else render_search(hits))
    return ExitCode.OK


def _reindex(args: list[str]) -> int:
    """`gaveta reindex` — backfill embeddings for items that lack them.

    Idempotent: a rerun with nothing new reports `embedded 0 of N`. Heals items
    captured while Ollama was down and re-embeds items whose text a retag changed. A
    model that returns a wrong-width vector is a usage error (the configured model
    does not fit this drawer), reported and refused — nothing is written.
    """
    argparse.ArgumentParser(prog="gaveta reindex", add_help=True).parse_args(args)

    try:
        embedder = make_embedder(load_config())
    except ConfigError as exc:
        print(f"[gaveta] {exc}", file=sys.stderr)
        return ExitCode.USAGE

    try:
        with db_session() as session:
            embedded, total = core.reindex(session=session, embedder=embedder)
    except core.DimensionMismatch as exc:
        print(
            f"[gaveta] ✗ {exc}. Change the model back, or delete item_embeddings "
            "and vec_items to rebuild under the new model.",
            file=sys.stderr,
        )
        return ExitCode.USAGE

    _emit(render_reindexed(embedded, total))
    return ExitCode.OK


DISPATCH: dict[str, Handler] = {
    "ls": _ls,
    "show": _show,
    "rm": _rm,
    "export": _export,
    "retag": _retag,
    "f": _f,
    "reindex": _reindex,
}
