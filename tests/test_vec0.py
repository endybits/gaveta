"""The sqlite-vec loader and the Vec0Store adapter.

This machine (and likely CI) cannot load sqlite-vec — the interpreter's sqlite3 was
built without extension loading — so the *real* vec0 path is covered two ways:

- The load-success arm of `_load_sqlite_vec` is driven with a **faked connection** that
  exposes stub `enable_load_extension`, so the branch runs without a real extension
  and coverage holds where it cannot load for real.
- `Vec0Store`'s SQL is asserted against a **recording fake session**, so the adapter's
  statements are covered deterministically everywhere.
- A `skipif`-guarded integration test runs the real adapter where the extension *does*
  load (a python.org / Debian Python), and skips cleanly here.

See docs/adr/ADR-005-semantic-retrieval.md.
"""

from typing import Any

import pytest

from gaveta.config import EMBEDDING_DIM
from gaveta.db import session as session_module
from gaveta.db.session import _load_sqlite_vec, vectors_available
from gaveta.search import Vec0Store, deserialize_vector, serialize_vector

# ── The load probe ────────────────────────────────────────────────────────────


class _FakeConn:
    """A DBAPI connection stub that records enable_load_extension calls."""

    def __init__(self) -> None:
        self.toggles: list[bool] = []

    def enable_load_extension(self, on: bool) -> None:
        self.toggles.append(on)


def test_load_succeeds_when_the_extension_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the success arm without a real extension: fake `sqlite_vec.load`.

    On a machine that cannot load extensions the real path returns False; here we
    prove the *other* branch — a connection that supports loading, and a
    `sqlite_vec.load` that succeeds, yields True and toggles extension loading on then
    off.
    """
    loaded: list[Any] = []

    class FakeSqliteVec:
        @staticmethod
        def load(conn: Any) -> None:
            loaded.append(conn)

    monkeypatch.setitem(__import__("sys").modules, "sqlite_vec", FakeSqliteVec)

    conn = _FakeConn()
    assert _load_sqlite_vec(conn) is True
    assert loaded == [conn]
    assert conn.toggles == [True, False]  # enabled, then disabled


def test_load_returns_false_when_enable_load_extension_is_missing() -> None:
    """The author's-machine reality: no `enable_load_extension` attribute at all.

    A plain object has no such method, so the call raises AttributeError, which the
    loader swallows into a clean False — the degraded path, never a crash.
    """

    class NoExtConn:
        pass

    assert _load_sqlite_vec(NoExtConn()) is False


def test_vectors_available_reflects_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_module, "_vectors_loaded", None)
    assert vectors_available() is False
    monkeypatch.setattr(session_module, "_vectors_loaded", True)
    assert vectors_available() is True


# ── Vec0Store SQL, asserted against a recording fake session ──────────────────


class _RecordingSession:
    """A stand-in Session that records executed statements and returns canned rows.

    Lets the Vec0Store adapter's SQL be exercised without a real vec_items table,
    which this machine cannot create.
    """

    def __init__(self, rows: list[tuple[int, float]] | None = None) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self._rows = rows or []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        self.statements.append((str(statement), params or {}))
        rows = self._rows

        class _Result:
            def fetchall(self) -> list[tuple[int, float]]:
                return rows

        return _Result()


def test_vec0_store_creates_the_table_on_construction() -> None:
    session = _RecordingSession()
    Vec0Store(session, dim=EMBEDDING_DIM)

    sql = session.statements[0][0]
    assert "CREATE VIRTUAL TABLE IF NOT EXISTS vec_items" in sql
    assert f"float[{EMBEDDING_DIM}]" in sql


def test_vec0_store_upsert_deletes_then_inserts() -> None:
    session = _RecordingSession()
    store = Vec0Store(session, dim=3)
    session.statements.clear()

    store.upsert(7, [0.1, 0.2, 0.3])

    delete_sql, delete_params = session.statements[0]
    insert_sql, insert_params = session.statements[1]
    assert "DELETE FROM vec_items" in delete_sql
    assert delete_params["id"] == 7
    assert "INSERT INTO vec_items" in insert_sql
    assert insert_params["id"] == 7
    # The stored bytes round-trip through the shared encoding.
    assert deserialize_vector(insert_params["v"]) == pytest.approx([0.1, 0.2, 0.3])


def test_vec0_store_search_builds_a_knn_query_and_maps_rows() -> None:
    session = _RecordingSession(rows=[(3, 0.1), (5, 0.4)])
    store = Vec0Store(session, dim=3)
    session.statements.clear()

    hits = store.search([1.0, 0.0, 0.0], k=2)

    sql, params = session.statements[0]
    assert "MATCH" in sql and "ORDER BY distance" in sql
    assert params["k"] == 2
    assert serialize_vector([1.0, 0.0, 0.0]) == params["v"]
    assert hits == [(3, 0.1), (5, 0.4)]


# ── The real adapter, only where the extension loads ──────────────────────────


@pytest.mark.skipif(
    not vectors_available(),
    reason="sqlite-vec cannot load on this interpreter (no enable_load_extension)",
)
def test_vec0_store_round_trips_against_a_real_extension() -> None:  # pragma: no cover
    """End-to-end on a vec-capable machine: upsert vectors, then a KNN query ranks them.

    Skipped where sqlite-vec cannot load (this machine, and CI unless the runner's
    Python enables extensions). Documented as verified manually and on a capable CI
    Python.
    """
    from gaveta.db.session import session as db_session

    with db_session() as session:
        store = Vec0Store(session, dim=EMBEDDING_DIM)
        near = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
        far = [0.0] * (EMBEDDING_DIM - 1) + [1.0]
        store.upsert(1, near)
        store.upsert(2, far)

        hits = store.search(near, k=2)
        assert hits[0][0] == 1  # the nearest vector ranks first
