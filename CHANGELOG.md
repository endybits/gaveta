# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Until `v1.0.0` the minor version tracks the stage number from
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## [Unreleased]

### Added

- `gv` is installed as a short alias for `gaveta`. Both console scripts share one entry
  point, so they cannot diverge.

### Changed

- The human view truncates `captured` to whole seconds
  (`2026-07-10T08:04:53-05:00`). Display only: `--json` keeps full microsecond precision
  and the `CaptureRequest` schema is unchanged.
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

[Unreleased]: https://github.com/endybits/gaveta/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/endybits/gaveta/compare/v0.0.1...v0.1.0
[0.0.1]: https://github.com/endybits/gaveta/releases/tag/v0.0.1
