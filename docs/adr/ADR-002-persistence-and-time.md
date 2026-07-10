# ADR-002 — Persistence: two models, and time is stored in UTC

- **Status:** Accepted
- **Date:** 2026-07-10
- **Stage:** 2 — Real persistence

## Context

Stage 2 is the first stage that writes to the user's disk. Two questions have to be answered
before a single row is written, and both are expensive to revisit once real drawers exist on
real machines:

1. **What is the relationship between the capture contract and the stored row?** Stage 1 froze
   `CaptureRequest` (pydantic) and snapshot-tested its JSON Schema. Stage 2 introduces `Item`
   (SQLAlchemy). Are these one model or two?
2. **How does a timestamp persist?** `CaptureRequest.captured_at` is timezone-aware and local.
   SQLite has no timezone type. Something has to give.

Both answers outlive this stage. Stage 4 widens classification, Stage 5 adds embeddings, and
Stage 7 serves these rows over HTTP with FastAPI — each of those inherits whatever is decided
here.

Two ADRs were considered. One was written: these are both "how data is stored", neither is large
enough to stand alone, and they are decided together or not at all. The Stage 4 model-choice
record, informally earmarked as ADR-002 during Stage 1, becomes **ADR-003**. An ADR is numbered
when it is written, not when it is imagined.

## Decision 1 — Two models, with a thin mapping layer

**`CaptureRequest` (pydantic, input) and `Item` (SQLAlchemy, row) stay separate, joined by
`gaveta/mapping.py`. A third model, `ItemView` (pydantic, output), is what `show`, `export`, and
`--json` emit.**

The one-model temptation is real — SQLModel exists precisely to collapse this distinction, and
collapsing it would delete a file. It is rejected on three grounds specific to this project.

### The schema snapshot is a contract test, and a merged model poisons it

`tests/__snapshots__/capture_request_schema.json` freezes the machine contract. Merge the ORM
into that model and every storage detail becomes a diff in the public contract: the `tags_json`
column name, an index, the embedding blob Stage 5 adds. Storage layout and public contract change
at different rates, for different reasons, and reviewed by different criteria. Two models is what
lets the contract stay frozen while the schema evolves under it.

The payoff is visible in this very stage. Capture's output contract changes — it now returns the
saved item, with its `id` — and because the change lands on a *new* model, `capture_request_schema.json`
shows **no diff at all**. A new `item_view_schema.json` appears beside it. A contract addition
reads as an addition.

### Stage 4 widens `type` on both sides, but not identically

The spec'd storage enum has five members from day one: `link | command | note | credential_ref |
unknown`. But `CaptureRequest.type` is `Literal["unknown"]` until classification lands in Stage 4 —
that narrowness is deliberate, tested, and the reason a caller cannot fabricate a classification
the system has not performed.

A single model cannot hold both truths. Two models means `CaptureType` (wire, narrow, widens at
Stage 4) and `ItemType` (storage, already the full five), and the mapping function is the one
place that states how the first becomes the second.

### Stage 7 needs a response model that is not a live ORM object

Returning an `Item` from a FastAPI route means either `from_attributes` — which *is* the mapping
layer, merely implicit and unreviewable — or handing a session-bound object to a serializer that
runs after the session closes, and meeting `DetachedInstanceError` in production. `ItemView` is
that response model. It is written now, used by the CLI now, and reused verbatim by the daemon
later.

### Cost

One `to_item(request) -> Item` and one `to_view(item) -> ItemView`, roughly fifteen lines. That
seam is also where Stage 3's gate verdict and Stage 4's classifier output attach, so the file
earns its keep twice.

## Decision 2 — Store UTC. Render local.

**Every datetime crossing into the database is timezone-aware and normalized to UTC. Every
datetime leaving it is timezone-aware. Naive datetimes do not exist in this codebase.**

This is not a preference between two workable options. A probe against the actual stack —
SQLAlchemy 2.0.51 on SQLite — removes one of them from the menu:

```python
aware = datetime.now().astimezone()      # 2026-07-10T08:37:52.175790-05:00
session.add(T(at=aware)); session.commit()
got = session.query(T).one().at          # 2026-07-10T08:37:52.175790   tzinfo=None
```

with the column declared, as one would think sufficient, `DateTime(timezone=True)`. The raw
column holds `2026-07-10 08:37:52.175790`.

**`DateTime(timezone=True)` is a no-op on SQLite.** The dialect writes the wall-clock digits,
discards the offset, and reads back a naive datetime. So "store local time with its offset" is
not an option that exists: SQLite has no type that holds it. What that choice actually delivers
is a *naive local timestamp* — a value that becomes silently wrong the moment the user changes
timezone or DST rolls over, and unrecoverably so, because the offset that would let you repair it
was thrown away at write time.

Therefore:

- **Store.** A `UtcDateTime(TypeDecorator)` normalizes on the way in (`.astimezone(UTC)`) and
  re-attaches `tzinfo=UTC` on the way out.
- **Reject, do not coerce.** A naive datetime arriving at the column raises `ValueError`. A naive
  datetime has no meaning — it could be any of 38 instants — and guessing that it means "local"
  is exactly the bug above, merely relocated into our own code.
- **Render.** `.astimezone()` at the display boundary, so a human sees their own clock. Symmetric
  with Stage 1, whose human view already prints a local offset.
- **Machine output.** `--json` and `export` emit UTC with an explicit `Z` suffix (pydantic's
  spelling of a zero offset). Unambiguous by construction; a consumer wanting local time can
  convert, and Stage 7's HTTP responses inherit this for free.

`created_at` is assigned in Python, never by `server_default=func.now()`. SQLite's
`CURRENT_TIMESTAMP` produces a naive UTC string that bypasses the `TypeDecorator` entirely,
reintroducing through the back door the exact value this decision exists to exclude.

## Decision 3 — Migrations live inside the package

**Alembic's `env.py`, `script.py.mako`, and `versions/` live at `src/gaveta/db/migrations/`, and
`script_location` is resolved from `gaveta.db.__file__` — never from the current directory.**

The schema is created by Alembic and only by Alembic. `Base.metadata.create_all()` appears nowhere
in `src/`: two paths to a schema means the migration chain is a fiction that only CI walks.

That rule and a repo-root `migrations/` directory are incompatible, and the incompatibility is
invisible until Stage 10. **The repo root does not ship in the wheel.** A user running
`pipx install gaveta-cli` would get a session factory that calls `command.upgrade()` against
migration scripts that are not on their disk: an installed Gaveta that can never create its own
database. Moving the directory into the package is what makes "exactly one path to a schema"
true for an *installed* Gaveta and not merely for a checkout.

Two probes confirm the mechanics:

- **Hatchling ships them with no extra configuration.** A wheel built from a package containing
  `db/migrations/{env.py, script.py.mako, versions/0001_init.py}` includes all three — the
  non-`.py` `.mako` template among them — with no `force-include` and no `__init__.py` in either
  directory.
- **Alembic requires no `alembic.ini` on disk.** `Config()` constructs with
  `config_file_name = None`; `script_location` and `sqlalchemy.url` are set programmatically and
  `command.upgrade(cfg, "head")` accepts the result.

`alembic.ini` remains at the repo root as a **developer convenience only** — it points at the
package location so `uv run alembic revision --autogenerate` works during development. Its
`sqlalchemy.url` is empty, and the URL is supplied programmatically from `db_path()`, so no one
can migrate the wrong database by standing in the wrong directory. Nothing under `src/` reads it.

## Consequences

**We accept** a mapping layer that must be updated when a field is added to both sides. That is
the cost of the seam, and the seam is where Stages 3 and 4 attach.

**We accept** that a caller cannot hand Gaveta a naive datetime. This will surface as a
`ValueError` the first time someone writes `datetime.now()` instead of `datetime.now(UTC)`, and
that is the intended outcome.

**We gain** a frozen input contract that survives a change to the output contract; a response
model Stage 7 can serve without touching a session; a timestamp that means the same instant on
every machine that ever reads the drawer; and an installed CLI that can create its own database.

**We give up** `DateTime(timezone=True)` as a meaningful declaration. It is retained in the column
definition for documentation value on backends where it *does* work, but the `TypeDecorator` — not
the dialect — is what enforces the invariant. A test asserts the invariant directly rather than
trusting the declaration.

## Revisiting this

Collapse the two models only if `CaptureRequest` and `ItemView` converge to the same field set
*and* the daemon has stopped serving ORM-adjacent objects — that is, essentially never; they
diverge further at Stage 4, not less.

Revisit UTC storage only on a move away from SQLite to a backend with a real `timestamptz`. Even
then the invariant ("aware in, aware out, UTC on the wire") should survive the migration; only the
`TypeDecorator` becomes redundant.
