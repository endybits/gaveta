# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Until `v1.0.0` the minor version tracks the stage number from
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## [Unreleased]

### Changed

- **`CaptureRequest.type` widened** from `unknown` to the wire vocabulary the classifier
  emits: `link`, `command`, `note`, `unknown`. `credential_ref` stays storage-only (the
  vault's, Stage 6). The `capture_request` JSON Schema snapshot changes accordingly — a
  deliberate contract diff.
- **`ItemView` gains `content`** (nullable). The output contract `show`, `export`, and
  `--json` emit now carries the copyable payload. The `item_view` JSON Schema snapshot
  changes accordingly — a deliberate contract diff.

### Added

- **Classification wired into capture.** The pipeline is now **scan → classify →
  persist**: after the gate clears (or redacts) the text, the classifier fills the saved
  item's type, title, tags, and content. The classifier only ever sees post-gate text —
  a blocked capture never reaches it, and on the redact path it is handed `[REDACTED]`,
  never the secret (both asserted by the pipeline-order test). A broken `config.toml`
  fails as a usage error (exit `2`) before any capture work begins.
- **The `content` column.** A nullable `content` column on `items`, added by an Alembic
  migration — the middle of the three layers (raw / content / title): the clean copyable
  payload with narrative stripped. Existing rows survive the upgrade with `content` NULL;
  the downgrade drops it cleanly.
- **Local classification (`gaveta.brain`).** A `Classifier` protocol with two
  implementations behind an Adapter: `OllamaClassifier` asks a local model for a strict
  JSON `{type, title, tags, content}`, and `HeuristicClassifier` is the deterministic
  floor it degrades to. Any failure — Ollama absent, connection refused, timeout, non-200,
  malformed or off-contract JSON — falls back to heuristics, so a capture is never lost.
  `httpx` reaches Ollama, importable only under `gaveta/brain` and only to localhost
  (ADR-004).
- **`~/.gaveta/config.toml`.** An optional config file (GAVETA_HOME-aware) with a `[model]`
  block: `name`, `endpoint`, `timeout`. Absent means defaults (`qwen2.5:3b-instruct` on
  `http://localhost:11434`, a 2.5s budget). A malformed file, or an endpoint that is not
  localhost, is a usage error (exit `2`) with a clear message — Gaveta never dials a
  non-local model (ADR-004).

## [0.3.0] — 2026-07-10

Stage 3 — the secret gate. A deterministic detector scans every capture *before* it is
written (and before any model in later stages sees it): known-format secrets are rejected,
ambiguous ones ask, and `--redact` masks what you choose to keep. Layers 1 and 3 of the
four-layer security model, documented honestly in `docs/security-model.md`.

### Added

- **The secret gate.** A deterministic detector, `gate.scan(raw) -> Verdict`, runs *first*
  in the capture pipeline — before persistence, and before any model in later stages.
  Known-format secrets (AWS keys, GitHub/Slack/Stripe tokens, PEM private-key headers,
  `user:pass@` connection URLs, JWTs) are **rejected with exit code `3`** and a message
  pointing at the vault flow (which lands for real in Stage 6). Patterns borrowed in shape
  from gitleaks/trufflehog.
- **High-entropy and context-word detection.** A long high-entropy token, or a value beside
  a bilingual keyword (`password`, `token`, `clave`, `contraseña`, …), rates *suspicious*
  and asks before saving — `[v]ault / [r]edact / [s]ave anyway` at a terminal. Over a pipe,
  where there is no terminal, a suspicious value is **blocked** rather than saved silently
  or hung on; the message names `--redact` and re-running interactively as the escape hatches.
- **`--redact`** masks each detected secret with `[REDACTED]` and saves the rest, from any
  source. It is the one path by which a detected secret may be stored — because the secret
  itself is not.
- [`docs/security-model.md`](docs/security-model.md): the four-layer defense (deterministic
  gate + contextual model + human confirmation + local-first containment), honest limits
  (no detector has 100% recall), and the exit-code table. Linked prominently from the README.
- [`docs/adr/ADR-003-secret-gate.md`](docs/adr/ADR-003-secret-gate.md): exit code `3`, the
  non-tty block policy, and the spans-carrying verdict model.
- `ExitCode(IntEnum)` — the CLI's exit codes are now named (`OK`/`NOT_FOUND`/`USAGE`/`BLOCKED`)
  instead of magic literals.

### Changed

- **A blocked secret exits `3`, distinct from the `2` used for usage errors.** A wrapper
  script can now tell "nothing to capture" from "that was a secret, and it was not saved."
- spec: Stage 4 gains content extraction; Stage 5 `-c` copies content.

## [0.2.0] — 2026-07-10

Stage 2 — real persistence. Captures are stored in a local SQLite database, and
`ls`/`show`/`rm`/`export` let you manage them. Schema changes go only through Alembic
migrations, from the first one.

### Added

- **Persistence.** Captures are saved to a local SQLite database at `~/.gaveta/gaveta.db`
  (overridable via `GAVETA_HOME`). Deleting the file resets the world.
- `gaveta ls [type]` lists captures newest first, optionally filtered by type;
  `gaveta show <id>` prints one in full; `gaveta rm <id>` removes one; `gaveta export`
  dumps every capture as a JSON array to stdout (`> backup.json` is the backup story).
- The `Item` model and an `items` table, created and evolved only by Alembic migrations —
  wired from the first migration, and shipped inside the package so an installed Gaveta
  can create its own database. Schema documented in [`docs/data-model.md`](docs/data-model.md).
- [`docs/adr/ADR-002-persistence-and-time.md`](docs/adr/ADR-002-persistence-and-time.md):
  two models with a mapping layer (input `CaptureRequest`, output `ItemView`), and UTC
  timestamp storage.
- `python -m gaveta` as a third invocation form, alongside the `gaveta` and `gv` scripts.
- Architecture tests fencing two CLAUDE.md invariants: no module imports a network library,
  and no `get_secret`-style symbol exists.

### Changed

- **Capture now persists and reports the id it assigned.** The confirmation is a terse
  one-liner — `✓ saved · id 1 · type unknown` — replacing Stage 1's five-line "would save"
  block, and `--json` returns the saved item (`ItemView`, id included) rather than the
  input `CaptureRequest`. A deliberate, additive contract change: a new
  `item_view_schema.json` snapshot lands with it, and `capture_request_schema.json` is
  unchanged.
- `ls`, `show`, `rm`, and `export` are no longer reserved words that exit `2` — they run.
  `retag`, `f`, `reindex`, `cred`, `daemon`, and `ui` remain reserved.
- Machine timestamps serialize as UTC with a `Z` suffix; the human views (`ls`, `show`)
  render in your local timezone, to the second.
- `gv` is installed as a short alias for `gaveta`. Both console scripts share one entry
  point, so they cannot diverge.
- The human view truncates timestamps to whole seconds. Display only: `--json` keeps full
  precision.
- Branches are now **rebase-merged** to `main` rather than squash-merged, so a stage's
  commit sequence survives. Every commit on a branch must leave the tree green, and the
  release tag goes on `chore: release vX.Y.Z`, which becomes `main`'s tip.

## [0.1.0] — 2026-07-10

Stage 1 — simulated capture (the walking skeleton). `gaveta "text"` shows what it *would*
save. Nothing is persisted; no model runs. This stage fixes the capture contract that
every later stage must honor.

### Added

- `gaveta "any text"` prints a structured, human-readable log of the capture that *would*
  be saved: `raw`, `type`, `tags`, `captured` (ISO-8601 with local offset), and `source`.
- `--json` emits the machine view: one JSON object per capture, on a single line. Its
  schema is snapshot-tested in `tests/__snapshots__/capture_request_schema.json`, so a
  contract change can only land as an explicit, reviewed diff.
- Stdin support: `echo "..." | gaveta -` and the bare `echo "..." | gaveta` are equivalent
  to the argument form.
- `CaptureRequest` (pydantic) — the capture model. `type` is fixed at `unknown` and `tags`
  at `[]` until Stages 4 and 2 give them meaning.
- Reserved command vocabulary (`gaveta.commands`): the ten commands the implementation plan
  grounds — `ls`, `show`, `rm`, `export`, `retag`, `f`, `reindex`, `cred`, `daemon`, `ui` —
  exit `2` with a message naming the stage that implements them. Matching is on the first
  token, so `gaveta ls links` is a reserved command while `gaveta "ls my files"` is text.
- `--version`, and `--` to capture text that begins with a dash.
- `docs/adr/ADR-001-cli-framework.md`, the project's first ADR: `argparse` over `typer`,
  with the probe evidence behind the choice.
- `pydantic` and `rich` as the first runtime dependencies.

### Changed

- Empty input exits `2` with a usage message. Empty or whitespace-only stdin counts as
  empty input, so behavior is identical on a terminal and on a CI runner, where stdin is
  never a tty.
- `gaveta` with no arguments no longer prints the version; use `gaveta --version`.

## [0.0.1] — 2026-07-09

Stage 0 — scaffolding & governance. No product behavior yet: `gaveta` prints its version.

### Added

- Project scaffolding: `pyproject.toml` (hatchling build, `gaveta-cli` distribution,
  `gaveta` console script) and the `src/gaveta/` package layout.
- `uv` as the environment manager, with `uv.lock` committed for reproducible installs.
  The `pip install -e ".[dev]"` path remains supported.
- Tooling: `ruff` (lint + format), `mypy --strict` on `src/`, `pytest` with coverage,
  and `pre-commit` hooks including a `commit-msg` hook enforcing Conventional Commits.
- CI (GitHub Actions): lint, typecheck, and a `pytest` matrix on Python 3.11/3.12/3.13,
  running in parallel on every push to `main` and every pull request.
- Smoke tests covering package import, the console-script entry point, and that
  `__version__` matches the installed distribution metadata.
- `CONTRIBUTING.md` and this changelog.

### Changed

- The default branch is now `main` (previously `master`).
- Coverage policy is now machine-enforced: `fail_under` in `pyproject.toml` is a ratchet
  that may only be raised at a stage close-out, never lowered. It starts at `90`.
- The version is read from installed distribution metadata rather than duplicated as a
  literal, so `pyproject.toml` is the single source of truth.

[Unreleased]: https://github.com/endybits/gaveta/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/endybits/gaveta/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/endybits/gaveta/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/endybits/gaveta/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/endybits/gaveta/releases/tag/v0.0.1
