# Contributing to Gaveta

Contributions are welcome from day zero — but so are the rules, from day zero.

## Getting set up

```bash
git clone https://github.com/endybits/gaveta && cd gaveta
uv sync                     # creates .venv and installs from uv.lock
uv run pre-commit install   # installs both the pre-commit and commit-msg hooks
uv run pytest
```

Without [uv](https://docs.astral.sh/uv/):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && pre-commit install && pytest
```

Everyday commands:

| Command | What it does |
|---|---|
| `uv run pytest` | Full suite, with coverage |
| `uv run pytest tests/test_gate.py::test_name -v` | A single test |
| `uv run ruff check . && uv run ruff format .` | Lint and format |
| `uv run mypy --strict src/` | Types (strict on `src/`, not `tests/`) |
| `uv run pre-commit run --all-files` | Everything the hooks check |

## The rules

### 1. Spec first

Every change maps to a numbered stage in [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
Each stage has a Spec, Scope, explicit Out of scope, Tests, Docs, and a Definition of Done.
A stage is not done until its DoD boxes are checked.

If your idea isn't covered by a stage, **the plan changes first, as its own explicit
commit** — open an issue proposing the spec change before writing code. Don't silently
implement ahead of the plan.

### 2. English everywhere

Code, comments, docstrings, commit messages, and docs are written in English.

### 3. Conventional Commits, one stage per branch

Commit types: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`. This is
enforced by a `commit-msg` hook — a non-conforming message is rejected locally, before it
ever reaches CI.

Branches are `stage/N-short-name` (e.g. `stage/1-simulated-capture`) or `fix/short-name`.
They are **rebase-merged** to `main` and tagged at stage close: `v0.0.1` for Stage 0,
`v0.N.0` for Stages 1–10.

Rebase, not squash. This project treats its history as part of what it ships: a stage's
commits show an ADR landing before the code it justifies, and a new dependency arriving as
its own reviewable one-line diff. Squashing a stage into a single commit keeps the outcome
and throws away the argument.

Two things follow, and both are on you as the author:

- **Every commit must leave the tree green.** Rebase replays your commits onto `main` one at
  a time, so each becomes a real point in `main`'s history. CI only gates the PR head — no
  check will catch a broken intermediate commit, so don't write one intending to fix it two
  commits later.
- **There is no merge commit.** Your last commit (`chore: release vX.Y.Z`) becomes `main`'s
  tip, and that is what gets tagged.

### 4. Tests are not optional

Every PR adds or updates tests. CI runs lint, `mypy --strict`, and `pytest` on Python
3.11/3.12/3.13; all must be green to merge.

**Coverage must not decrease.** This is enforced by `fail_under` in `pyproject.toml`, and it
is a ratchet: the floor **may only be raised, never lowered**. It is raised to the measured
value at each stage close-out. Lowering it requires an explicit spec change, reviewed on its
own merits.

Tests never touch your real home directory — isolate via `GAVETA_HOME`. Tests never use the
network or a real model: mock `OllamaClassifier`, use a deterministic fake embedder, use
`FakeVaultProvider`, and mock subprocess calls to `bw` / `keepassxc-cli`.

### 5. Docs close the loop

If behavior changed, the README/docs and `CHANGELOG.md` (under *Unreleased*) change in the
same PR.

### 6. Security is a hard boundary

No PR may introduce a code path where a secret value is returned, logged, or persisted.

The `VaultProvider` protocol deliberately exposes only `exists(ref)`,
`copy_to_clipboard(ref)`, and `open_in_app(ref)`. **A `get_secret()`-style function must
never exist.** An architecture test scans for such symbols and fails the suite if one
appears. Do not work around it — the absence of that API *is* the security property.

Likewise, the secret gate runs *first* in the capture pipeline, before persistence and
before any model sees the input. A pipeline-order test asserts this.

**Fixture hygiene — test secrets must be defanged or runtime-assembled.** The gate's test
corpus (`tests/fixtures/secret_corpus.py`, reused by the Stage 9 MCP redaction pass) is
full of strings *shaped* like secrets. They must be public documentation examples (AWS's
`AKIAIOSFODNN7EXAMPLE`, the jwt.io sample) or clearly synthetic — never a real-looking
generated token. Two hard-won rules:

- **GitHub push protection matches provider *prefixes* server-side and honors no repo
  config.** It fires on `xoxb-`, `sk_live_`, `AKIA…`, etc. regardless of the body — a fake
  `sk_live_EXAMPLENOTREAL…` is still blocked, and `.gitleaks.toml` does **not** apply to it.
  So a scanner-clean repo cannot be achieved by an allowlist alone.
- **Never commit a whole provider-prefixed literal, even a canonical doc example**, unless
  GitHub itself allowlists it (it does for a handful, like `AKIAIOSFODNN7EXAMPLE`). Defang
  the body (`xoxb-EXAMPLE-NOT-REAL-…`) *and*, where the prefix alone trips the scanner
  (Stripe), **assemble the value at runtime** so the literal never appears whole in source
  (`f"sk{_LIVE}…"`). The gate scans the assembled string exactly as it would a real one, so
  detection is unchanged. `.gitleaks.toml` allowlists the fixtures path as a second layer,
  not the only one.

If a push is rejected for a secret, do not `--force` past it or unblock via the URL — fix
the fixture so no commit contains the literal (rewrite the introducing commit, not a patch
on top), then re-push.

### 7. Small PRs, honest descriptions

A PR description states what the spec asked, what you did, how you tested it, and carries
the stage's DoD checklist. This is the project's narrative history — write it even when
working solo.

## Architecture decisions

ADRs live in `docs/adr/` and are written as part of the stage that needs them. Record the
decision when you make it, not after.

## License

By contributing you agree that your contributions are licensed under
[Apache 2.0](LICENSE).
