# Gaveta — Implementation Plan (Spec-Driven, Incremental)

> Everything you need, right where you left it.

This plan follows a **spec-driven design** approach: every stage begins with a written
spec (the behavior contract), is implemented in the smallest useful increment, and
**closes with passing tests and updated documentation**. No stage is "done" until its
Definition of Done checklist is complete.

**Guiding principles**

1. **Walking skeleton first.** Stage 1 only *simulates* saving (structured log output).
   Every later stage deepens one axis at a time.
2. **Secrets never enter the system.** The secret gate (Stage 3) lands *before* any
   model sees user input. `credential_ref` is metadata only; a `get_secret() -> str`
   function must never exist in the codebase (enforced by an architecture test).
3. **Core is the product; interfaces are clients.** CLI, Web UI, and MCP all talk to
   the same core API. Nothing interface-specific leaks into the core.
4. **History is part of the product.** Conventional commits, one stage per branch,
   **rebase-merged** so every commit survives on `main`, tagged at every stage close.
   The sequence *is* the argument: an ADR lands before the code it justifies, a new
   dependency is its own reviewable diff. Squashing a stage into one blob throws that
   away and leaves only the outcome. Corollary: **every commit on a stage branch must
   leave the tree green**, because rebase replays each one onto `main` individually.

---

## Repository conventions (apply from minute zero)

| Concern | Rule |
|---|---|
| Language | All code, comments, docstrings, and docs in **English** |
| License | Apache 2.0 |
| Commits | [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:` |
| Branches | `stage/N-short-name` (e.g. `stage/1-simulated-capture`), **rebase-merge** to `main`; every commit must leave the tree green |
| Tags | `v0.N.0` at each stage close (stage number = minor version until 1.0) |
| Tests | `pytest`; every stage adds tests; CI must be green to merge |
| Style | `ruff` (lint + format), `mypy --strict` on `src/` |
| Python | 3.11+ · package name on PyPI: `gaveta-cli` · installed commands: `gaveta` and `gv` (alias, same entry point) |
| Environment | `uv` (`uv sync`, `uv run …`); `uv.lock` is committed. `pip install -e ".[dev]"` remains supported |
| Layout | `src/gaveta/` layout, `tests/`, `docs/` |

---

## Stage 0 — Scaffolding & governance

**Spec.** A contributor can clone the repo, run one command, and get a working dev
environment with lint, types, and tests wired. The repo communicates its rules
without anyone having to ask.

**Scope**
- `pyproject.toml` (project metadata, `gaveta = "gaveta.cli:main"` entry point), built with
  `hatchling`; `uv` manages the environment and `uv.lock` is committed for reproducible CI.
- `src/gaveta/__init__.py` exposing `__version__`, derived from installed distribution
  metadata (`importlib.metadata`) so the version lives only in `pyproject.toml`.
- Tooling: `ruff`, `mypy`, `pytest`, `pre-commit` (ruff + conventional-commit hook via
  `commitizen`).
- CI (GitHub Actions): lint, typecheck, and a test matrix on push/PR.
- `README.md`, `LICENSE` (Apache 2.0), `CONTRIBUTING.md` (extracted from README rules),
  `CHANGELOG.md` (Keep a Changelog format).

**Out of scope.** Any product behavior.

**Tests.** One smoke test: `import gaveta; assert gaveta.__version__`.

**Docs.** README badges (CI status), dev quickstart section.

**Definition of Done**
- [ ] `uv sync && uv run pytest` green locally and in CI
- [ ] `pip install -e ".[dev]" && pytest` (the no-uv path) green
- [ ] `pre-commit run --all-files` clean, and `.git/hooks/commit-msg` rejects a
      non-conventional commit message
- [ ] Tag `v0.0.1`

---

## Stage 1 — Simulated capture (the walking skeleton)

**Spec.** `gaveta "any text"` accepts input and emits a structured, human-readable
log of *what would be saved* — no persistence, no model, no magic. This validates the
CLI ergonomics and fixes the capture contract that every later stage must honor.

```
$ gaveta "ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database"
[gaveta] would save:
  raw      : ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database
  type     : unknown   (classification lands in Stage 4)
  tags     : []
  captured : 2026-07-09T14:03:11-05:00
  source   : cli
```

**Scope**
- CLI entrypoint (`typer` or `argparse` — decide and record in ADR-001).
- `CaptureRequest` dataclass/pydantic model: `raw`, `source`, `captured_at`.
- Structured logging (`rich` for the human view; `--json` flag for machine view).
- Stdin support: `echo "..." | gaveta -`.

**Out of scope.** Persistence, classification, secret detection.

**Tests**
- CLI invocation returns exit code 0 and prints the expected fields.
- `--json` output validates against the `CaptureRequest` schema.
- Stdin pipe path covered.

**Docs.** README: real usage example replaces placeholder. `docs/adr/ADR-001-cli-framework.md`.

**Definition of Done**
- [ ] A human can run `gaveta "text"` and *see* what would be saved
- [ ] JSON contract snapshot-tested
- [ ] CHANGELOG + tag `v0.1.0`

---

## Stage 2 — Real persistence

**Spec.** Captures are stored in a local SQLite database. `gaveta ls` lists recent
items. Deleting the DB file resets the world. Schema changes only via migrations.

**Scope**
- SQLAlchemy models: `Item(id, raw, type, title, tags_json, created_at, updated_at)`.
  `type` is an enum: `link | command | note | credential_ref | unknown`.
- Alembic wired from the first migration (no "we'll add migrations later").
- DB location: `~/.gaveta/gaveta.db` (XDG-aware), overridable via `GAVETA_HOME`.
- Commands: `gaveta ls [type]`, `gaveta show <id>`, `gaveta rm <id>`.
- `gaveta export` → JSON dump (backup story starts now, it's cheap).

**Tests**
- CRUD roundtrip; `ls` ordering; `rm` idempotence.
- Alembic upgrade/downgrade on a temp DB.
- `GAVETA_HOME` isolation (tests never touch the real home).

**Docs.** README commands table; `docs/data-model.md` with the schema.

**Definition of Done**
- [ ] Save → restart process → `gaveta ls` shows the item
- [ ] Migrations run clean up and down
- [ ] CHANGELOG + tag `v0.2.0`

---

## Stage 3 — Secret gate (deterministic detector)

**Spec.** Before *anything* else touches the input — including any model in later
stages — a deterministic detector scans it. Known-format secrets (AWS keys, GitHub/
Slack/Stripe tokens, PEM blocks, `user:pass@` connection strings, JWTs) are **rejected
by default** with a clear message and a hint toward the vault flow. High-entropy
candidates trigger an interactive confirmation: `[v]ault / [r]edact / [s]ave anyway`.

```
$ gaveta "deploy key: AKIAIOSFODNN7EXAMPLE"
[gaveta] ✋ blocked: input contains what looks like an AWS access key.
         Secrets never enter Gaveta. Store it in your vault and save a
         reference instead:  gaveta cred --new
```

**Scope**
- `gaveta.gate` module: regex ruleset (borrowing patterns from gitleaks/trufflehog)
  + Shannon-entropy heuristic with context words (`password`, `pwd=`, `token`, `clave`).
- Pipeline contract: `gate.scan(raw) -> Verdict(clean | suspicious | blocked)` runs
  first in the capture flow, always.
- `--redact` writes the item with `[REDACTED]` placeholders.

**Out of scope.** Vault integration itself (Stage 6) — for now the block message
points to the future flow.

**Tests**
- Fixture corpus: ≥30 known-format secrets → **100% must be blocked** (hard assert).
- Benign high-entropy corpus (git SHAs, UUIDs) → suspicious at most, never silently saved without the confirm path.
- Property test: gate always runs before persistence (pipeline order test).

**Docs.** `docs/security-model.md` — the flagship doc: layered defense, honest limits
(no detector guarantees 100% recall), containment story. README links it prominently.

**Definition of Done**
- [ ] Corpus tests green, pipeline-order test green
- [ ] Security model documented honestly
- [ ] CHANGELOG + tag `v0.3.0`

---

## Stage 4 — Local classification & tagging

**Spec.** After the gate clears input, a local model (Ollama) classifies the item
(`link | command | note`), extracts a short title, and proposes tags. If Ollama is
unavailable, Gaveta degrades gracefully to heuristics (URL regex → `link`; shell-ish
tokens → `command`; else `note`) and never blocks capture.

**Scope**
- `gaveta.brain` module behind a `Classifier` protocol: `OllamaClassifier` +
  `HeuristicClassifier` fallback (Adapter pattern).
- Model configurable (`~/.gaveta/config.toml`), default: a small instruct model
  (evaluate Qwen 2.5 3B vs. Gemma small against 20 real samples — record in ADR-002).
- Strict JSON contract with the model; malformed output → fallback, never crash.
- The classifier additionally extracts `content`: the clean, usable payload of the
  item — the bare command, the bare URL, the bare snippet — stripped of the
  surrounding narrative. `raw` remains the immutable original as captured; `title`
  remains the short human label. Three layers: raw (everything), content (the
  copyable part), title (the readable label). `content` is a new nullable column
  added via Alembic migration in Stage 4; `retag <id>` re-extracts it along with
  type/title/tags. The heuristic fallback (no Ollama) sets content only for
  trivially extractable cases (a lone URL) and leaves it null otherwise.
- `gaveta retag <id>` to reclassify.

**Tests**
- `OllamaClassifier` fully mocked: contract tests on prompt in / JSON out.
- Fallback heuristics unit-tested; "Ollama down" path tested.
- End-to-end: capture → classified item persisted with type ≠ unknown.

**Docs.** README: requirements section (Ollama optional). ADR-002 model choice.

**Definition of Done**
- [ ] Works with and without Ollama installed
- [ ] CHANGELOG + tag `v0.4.0`

---

## Stage 5 — Semantic retrieval

**Spec.** `gaveta f "query"` finds items by meaning, not keywords. Top hits render
with id, type, title. `-c` copies the best hit's payload to the clipboard.

**Scope**
- Embeddings via Ollama embedding model; stored in `sqlite-vec` virtual table.
- Hybrid ranking: vector similarity + FTS5 keyword score (simple reciprocal fusion).
- Backfill command: `gaveta reindex`.
- Clipboard via `pyperclip` (with a no-clipboard fallback that prints).
- `-c` copies `content` when present, falling back to `raw`. Rationale: the promise
  of retrieval is paste-ready output; prose glued to a SQL query is the friction this
  product exists to remove.

**Tests**
- Deterministic fake embedder in tests (no network, no model).
- Relevance smoke: seeded corpus where the expected item must rank top-3.
- `reindex` idempotence.

**Docs.** README retrieval examples; `docs/search.md` on ranking.

**Definition of Done**
- [ ] "túnel rds qa" finds the SSH tunnel command from Stage 1's example
- [ ] CHANGELOG + tag `v0.5.0`

---

## Stage 6 — Vault integration (`credential_ref`)

**Spec.** Credentials live in an external vault (Bitwarden CLI or KeePassXC).
Gaveta stores only references. `gaveta cred <name>` resolves the ref and sends the
secret **directly to the clipboard** with auto-clear; the value never crosses stdout,
logs, the DB, or any model context.

**Scope**
- `VaultProvider` protocol: `exists(ref)`, `copy_to_clipboard(ref)`, `open_in_app(ref)`.
  **Deliberately no `get_secret()`** — enforced by an architecture test that fails the
  suite if any such symbol appears.
- `BitwardenProvider` (session token held in daemon/process memory only, TTL,
  passed per-call, never in env of child processes) and `KeePassXCProvider`
  (stateless, uses `keepassxc-cli clip` with auto-clear).
- `gaveta cred --new`: guided flow → creates vault entry → saves `credential_ref`.
- Gate integration: Stage 3's block message now offers this flow for real.

**Tests**
- `FakeVaultProvider` for all flows; subprocess calls mocked.
- Architecture test: grep/AST assert no `get_secret` and no secret-bearing return types.
- Session lifecycle: TTL expiry → re-unlock prompt path.

**Docs.** `docs/vault.md` setup guides for both providers; security-model doc updated.

**Definition of Done**
- [ ] End-to-end with a real Bitwarden test vault (manual checklist in PR)
- [ ] Architecture test green
- [ ] CHANGELOG + tag `v0.6.0`

---

## Stage 7 — Core daemon & local HTTP API

**Spec.** The core becomes a long-lived local daemon (FastAPI on `127.0.0.1`, port
configurable). The CLI becomes a thin client. Single source of truth for capture,
search, and vault flows. This is the seam that later enables Web UI, MCP, and the
future droplet deployment without rewrites.

**Scope**
- `gaveta daemon start|stop|status`; CLI auto-starts the daemon if absent.
- REST endpoints mirroring the CLI verbs; OpenAPI schema published.
- Loopback-only binding; simple bearer token stored in `~/.gaveta/` (0600).

**Tests**
- API contract tests via `httpx` TestClient.
- CLI↔daemon integration: same behavior as pre-daemon (regression suite reused).

**Docs.** `docs/architecture.md` updated with the client/core diagram.

**Definition of Done**
- [ ] All previous CLI tests pass unchanged against the daemon-backed CLI
- [ ] CHANGELOG + tag `v0.7.0`

---

## Stage 8 — Read-only Web UI

**Spec.** `gaveta ui` opens a minimal localhost view: items grouped by type, tag
filter, semantic search box. Read-only in this stage.

**Scope**
- Served by the daemon (no separate process): HTMX or a small React bundle — ADR-003.
- Views: category browse, item detail, search.

**Tests.** Endpoint/render tests; search parity with CLI results.

**Docs.** README screenshot; `gaveta ui` in commands table.

**Definition of Done**
- [ ] CHANGELOG + tag `v0.8.0`

---

## Stage 9 — MCP server with sanitization policy

**Spec.** A FastMCP (stdio) server exposes Gaveta to Claude Desktop/Code and any MCP
client. Policy: `search`, `save`, `get_item` never return `credential_ref` payloads —
only metadata plus the copy instruction. A `copy_credential(ref)` tool triggers the
clipboard flow and returns confirmation, never the value. A redaction pass re-scans
every outbound payload (second chance for the gate).

**Tests**
- MCP tool contract tests; redaction pass corpus (reuse Stage 3 fixtures).
- Policy test: crafted `credential_ref` items can never appear in tool outputs.

**Docs.** `docs/mcp.md` with Claude Desktop setup snippet; security model updated.

**Definition of Done**
- [ ] Manual E2E with Claude Desktop documented in the PR
- [ ] CHANGELOG + tag `v0.9.0`

---

## Stage 10 — Packaging & first public release

**Spec.** A stranger can install and use Gaveta in under two minutes.

**Scope**
- PyPI release as `gaveta-cli` (command: `gaveta`) via CI on tag.
- `pipx` as the blessed install path; optional Homebrew tap.
- Versioning automation (`commitizen` or `release-please` from conventional commits).
- Issue templates, PR template, `SECURITY.md` (responsible disclosure).

**Definition of Done**
- [ ] `pipx install gaveta-cli` works from a clean machine
- [ ] Tag `v1.0.0` 🎉

---

## Backlog (post-1.0, deliberately not now)

- Remote core deployment (droplet/VPC) behind Tailscale — architecture already supports it.
- Multi-device sync strategy.
- Write actions in Web UI.
- Browser extension / share-sheet capture.
- Pluggable vault providers (1Password `op`, pass).

---

## Working agreement per stage (the loop)

1. Open `stage/N-name` branch. First commit: the spec section of this file updated
   if reality diverged (spec is living, but changes are explicit commits).
2. Implement in small conventional commits.
3. Tests green, and the coverage ratchet holds: `fail_under` in `pyproject.toml` is the
   floor. A stage-closing PR **may raise it** to the newly measured value; it **may never
   lower it**. Raising is optional, lowering requires an explicit spec change. The floor
   starts at `90` in Stage 0 — deliberate slack, not the measured value, so that the first
   real code does not fail CI by definition.
4. Update README/docs touched by the stage. Update CHANGELOG under `Unreleased`.
5. **Last commit on the branch**: move the `Unreleased` CHANGELOG entries under the new
   version (`docs: release vX.Y.Z changelog`). Doing this after the merge would mean a
   direct commit on `main`, outside a PR — which this flow forbids and branch protection
   blocks outright.
6. **Rebase-merge** the PR (PR description = spec + DoD checklist, even solo). Every commit
   replays onto `main` with a new SHA, so `main` stays linear *and* keeps the stage's
   reasoning. Then tag and push.

   Rebase-merge produces **no merge commit**: the branch's last commit —
   `chore: release vX.Y.Z` from step 5 — becomes `main`'s tip, and that is what gets tagged.
   The tag therefore points at the commit that sets the version, which is what you want.

   Because each commit lands on `main` on its own, each must be green on its own. CI only
   gates the PR head, so this is a discipline, not a check: don't commit a broken
   intermediate state intending to fix it two commits later.
