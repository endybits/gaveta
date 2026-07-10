# Gaveta

> Everything you need, right where you left it.

**Gaveta** (Spanish for *drawer* — the one where you keep the things you reach for
every day) is a local-first, private knowledge drawer for developers. Throw in links,
commands, and notes as unstructured text; a small local model classifies, tags, and
indexes them; retrieve them later by *meaning*, not by remembering where you put them.

```
$ gaveta "ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database"
✓ saved as command · tagged: ssh, rds, qa

$ gaveta f "how did I connect to the qa database?"
1. [command] SSH tunnel to qa RDS   →  gaveta show 42 · -c to copy
```

## Security model (read this first)

**Secrets never enter Gaveta.** A deterministic secret gate scans every capture
*before* anything else — including any model — sees it. Passwords, API keys, and
tokens are rejected and redirected to your real vault (Bitwarden or KeePassXC).
Gaveta stores only *references*; resolving one sends the secret straight from the
vault to your clipboard, never through Gaveta's storage, logs, or model context.

No detector is perfect, so the design assumes escapes: everything is local
(SQLite on your machine), nothing is sent to any external API, and outbound
interfaces (like the MCP server) apply a second redaction pass.

Full details: [`docs/security-model.md`](docs/security-model.md).

## Status

🚧 **Pre-alpha — under active, incremental development.**
We are building in public, stage by stage, spec first. See
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) for the roadmap and the current
stage. Nothing below is stable until `v1.0.0`.

## Basic commands (target CLI)

| Command | What it does |
|---|---|
| `gaveta "some text"` | Capture anything — classification is automatic |
| `echo "..." \| gaveta -` | Capture from stdin / clipboard pipe |
| `gaveta f "query"` | Semantic find (`-c` copies best hit to clipboard) |
| `gaveta ls [type]` | Browse by category (`link`, `command`, `note`, `cred`) |
| `gaveta cred <name>` | Resolve a credential ref → vault → clipboard (auto-clear) |
| `gaveta cred --new` | Create a vault entry + save its reference |
| `gaveta ui` | Open the local web view |
| `gaveta export` | JSON backup of your drawer |

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) (optional but recommended — enables classification
  and semantic search; without it Gaveta degrades to simple heuristics)
- Bitwarden CLI (`bw`) or KeePassXC (`keepassxc-cli`) for the credentials flow (optional)

## Development quickstart

Gaveta uses [uv](https://docs.astral.sh/uv/) to manage the environment.

```bash
git clone https://github.com/endybits/gaveta && cd gaveta
uv sync                     # creates .venv and installs everything, from uv.lock
uv run pre-commit install   # installs both pre-commit and commit-msg hooks
uv run pytest
```

Without `uv`, the classic path still works:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" && pre-commit install && pytest
```

## Contributing

Contributions are welcome from day zero — but so are the rules, from day zero:

1. **Spec first.** Every change maps to a stage in
   [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md). If your idea isn't covered,
   open an issue proposing the spec change before writing code.
2. **English everywhere in the repo.** Code, comments, docstrings, commit messages,
   and docs are written in English.
3. **Conventional Commits.** `feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
   `chore:`. Enforced by pre-commit. Branches: `stage/N-name` or `fix/short-name`.
4. **Tests are not optional.** Every PR adds or updates tests; CI (lint → mypy →
   pytest) must be green. Coverage must not decrease.
5. **Docs close the loop.** If behavior changed, the README/docs and `CHANGELOG.md`
   (under *Unreleased*) change in the same PR.
6. **Security is a hard boundary.** No PR may introduce a code path where a secret
   value is returned, logged, or persisted. The architecture tests enforce the
   absence of `get_secret`-style APIs — do not fight them.
7. **Small PRs, honest descriptions.** PR description = what the spec asked,
   what you did, how you tested it, and the stage's DoD checklist.

By contributing you agree that your contributions are licensed under Apache 2.0.

## License

[Apache 2.0](LICENSE)
