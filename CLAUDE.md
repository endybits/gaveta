# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Stage 0 (scaffolding) has landed: `pyproject.toml`, `src/gaveta/`, tooling, and CI exist. The
package has **no product behavior yet** — `gaveta.cli:main` is a stub that prints the version;
the real CLI arrives in Stage 1 along with ADR-001. Do not assume a command from a later stage
runs until the stage that introduces it has landed.

## Spec-driven workflow (non-negotiable)

`IMPLEMENTATION_PLAN.md` is the contract, not a wishlist. Every change maps to a numbered stage there. Each stage has a **Spec**, **Scope**, explicit **Out of scope**, **Tests**, **Docs**, and a **Definition of Done** checklist — a stage is not done until its DoD boxes are checked.

- If a request isn't covered by a stage, the plan changes first, as its own explicit commit. Don't silently implement ahead of the plan.
- Work happens on `stage/N-short-name` (or `fix/short-name`), squash-merged to `main`, tagged at stage close: `v0.0.1` for Stage 0, `v0.N.0` for Stages 1–10.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), enforced by pre-commit.
- Everything in the repo is written in English — code, comments, docstrings, commits, docs.
- Behavior change ⇒ README/docs and `CHANGELOG.md` (under *Unreleased*) change in the same PR.

Stages, in order: 0 scaffolding · 1 simulated capture · 2 SQLite persistence · 3 secret gate · 4 local classification · 5 semantic retrieval · 6 vault integration · 7 daemon + HTTP API · 8 read-only web UI · 9 MCP server · 10 packaging/v1.0.0.

## Commands

The environment is managed by `uv`; `uv.lock` is committed.

```bash
uv sync                      # create .venv and install everything from the lockfile
uv run pre-commit install    # installs both pre-commit and commit-msg hooks

uv run pytest                # full suite
uv run pytest tests/test_gate.py::test_name -v   # single test
uv run ruff check . && uv run ruff format .
uv run mypy --strict src/    # strict typing is required on src/, not tests/
uv run pre-commit run --all-files
```

Without `uv`: `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`,
then run the same commands without the `uv run` prefix.

CI runs lint, mypy, and pytest — all three must be green to merge. They run as parallel jobs;
"lint → mypy → pytest" is an ordering of severity, not of execution.

Coverage must not decrease between stages, enforced by `fail_under` in `pyproject.toml`. That
floor may only be **raised** (at a stage close-out, to the measured value), never lowered;
lowering requires an explicit spec change.

The version lives in exactly one place: `version` in `pyproject.toml`. `gaveta.__version__`
reads it back via `importlib.metadata`. Never hardcode a version literal in `src/`.

## Working on this repo safely

**Never `git reset --hard` with a dirty working tree.** `--hard` discards uncommitted
changes, including ones you did not make and may not have read. Stash or commit first. To
undo a throwaway probe commit, use `git reset --soft HEAD~1` or `git commit --amend`. A
human's uncommitted work is not yours to discard.

**Pin GitHub Actions to a tag that exists.** Do not infer a floating major alias (`@v8`)
from a point release (`v8.3.2`) — not every action publishes one, and the job then fails at
setup before running anything. Verify with `git ls-remote --tags`, prefer an exact pin, and
say why in a comment. Dependabot keeps exact pins fresh.

**Some failures only exist on the runner.** Local verification cannot catch a bad action
ref, a matrix-only break, or a stale lockfile. This is why every stage's DoD requires green
CI, not just a green local run.

## Architecture invariants

These constraints shape the code and are enforced by tests — they are not style preferences.

**Secrets never enter the system.** A deterministic secret gate (`gaveta.gate`, Stage 3) runs *first* in the capture pipeline, before persistence and before any model ever sees the input. `gate.scan(raw) -> Verdict(clean | suspicious | blocked)`. A pipeline-order test asserts the gate precedes persistence.

**`get_secret()` must never exist.** The `VaultProvider` protocol (Stage 6) deliberately exposes only `exists(ref)`, `copy_to_clipboard(ref)`, `open_in_app(ref)`. Secret values go vault → clipboard directly, never through Gaveta's return values, stdout, logs, DB, or model context. An architecture test greps/AST-scans for `get_secret`-style symbols and fails the suite if one appears. Do not work around it — the absence of the API *is* the security property.

**Core is the product; interfaces are clients.** CLI, Web UI, and MCP all call the same core API (which becomes a local FastAPI daemon in Stage 7). Nothing interface-specific may leak into the core. This seam is what makes the daemon, MCP server, and any future remote deployment possible without a rewrite.

**Defense assumes the detector leaks.** No secret detector has perfect recall, so containment matters as much as detection: everything stays local (SQLite at `~/.gaveta/gaveta.db`, overridable via `GAVETA_HOME`), nothing is sent to an external API, and outbound interfaces (MCP) apply a second redaction pass over every payload.

**Degrade, never block.** The local model (Ollama) is optional. When it's absent or returns malformed JSON, classification falls back to heuristics (URL regex → `link`, shell-ish tokens → `command`, else `note`). Capture must never crash or hang on a missing model.

## Testing conventions

- Tests never touch the real home directory — isolate via `GAVETA_HOME`.
- No network and no real model in tests: mock `OllamaClassifier`, use a deterministic fake embedder, use `FakeVaultProvider`, mock subprocess calls to `bw`/`keepassxc-cli`.
- The Stage 3 secret corpus (≥30 known-format secrets) is a hard assert: 100% must be blocked. The same fixtures are reused for the Stage 9 MCP redaction pass.
- Benign high-entropy strings (git SHAs, UUIDs) may be flagged `suspicious` but must never be silently saved without the confirmation path.

## Architecture decisions

ADRs live in `docs/adr/` and are written as part of the stage that needs them (ADR-001 CLI framework, ADR-002 model choice, ADR-003 web UI stack). Record the decision when you make it, not after.
