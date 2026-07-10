# Gaveta

[![CI](https://github.com/endybits/gaveta/actions/workflows/ci.yml/badge.svg)](https://github.com/endybits/gaveta/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

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

☝️ That is the destination. **What actually runs today** persists captures to a local
database and lets you list, show, remove, and export them — see
[What works right now](#what-works-right-now).

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

## What works right now

**Stage 2 — real persistence.** Captures are stored in a local SQLite database at
`~/.gaveta/gaveta.db`. You can list, show, remove, and export them. No model runs yet
(classification is Stage 4) and no secret gate runs yet (Stage 3), so every capture is
saved verbatim and typed `unknown`.

```
$ gaveta "ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database"
✓ saved · id 1 · type unknown

$ gaveta ls
     1  unknown         ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database

$ gaveta show 1
  id      : 1
  raw     : ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database
  type    : unknown
  title   : —
  tags    : —
  created : 2026-07-10T09:14:03-05:00
  updated : 2026-07-10T09:14:03-05:00
```

Pipe it instead, with `-` or on its own — the two are equivalent:

```
$ echo "remember this" | gaveta -
$ pbpaste | gaveta
```

`--json` returns the saved item — id included — as one JSON object. This is the machine
contract every later stage honors, and it is snapshot-tested, so it cannot drift by
accident. `created_at` is UTC (`Z`); the human views show your local time.

```
$ gaveta "x" --json
{"id":2,"raw":"x","type":"unknown","title":null,"tags":[],"created_at":"2026-07-10T14:14:03.482Z","updated_at":"2026-07-10T14:14:03.482Z"}
```

Manage what you have captured:

| Command | What it does |
|---|---|
| `gaveta ls [type]` | List captures, newest first; optionally filter by type |
| `gaveta show <id>` | Show one capture in full |
| `gaveta rm <id>` | Remove one (idempotent — a second `rm` of the same id is fine) |
| `gaveta export` | Dump every capture as a JSON array to stdout |

`gaveta export > backup.json` is the backup story; redirection is the file, so there is no
`--output` flag. **Deleting `~/.gaveta/gaveta.db` resets the world** — the next command
re-creates it, empty. Full schema in [`docs/data-model.md`](docs/data-model.md).

Three things worth knowing:

- **`gv` is an alias for `gaveta`.** Both commands are installed and point at the same
  entry point, so `gv ls` and `gv "some text"` work with less typing.
- **Reserved words.** `retag`, `f`, `reindex`, `cred`, `daemon`, and `ui` are reserved for
  the stages that implement them; `gaveta f "query"` exits with a message naming its stage
  rather than capturing "f". To capture a reserved word as text, use `gaveta -- "f"`.
- **Text starting with a dash.** A bare `-L` looks like an option to any argument parser.
  Quoted text with a space (`gaveta "ssh -L 5432"`) is fine; a lone dash token needs
  `gaveta -- "-L"`, or pipe it in.

Empty input (no argument, nothing piped) prints usage and exits `2`.

## Basic commands (target CLI)

The rest of the destination, not yet implemented. See
[What works right now](#what-works-right-now) for what runs today.

| Command | What it does | Status |
|---|---|---|
| `gaveta "some text"` | Capture anything — classification is automatic | capture works; classification is Stage 4 |
| `echo "..." \| gaveta -` | Capture from stdin / clipboard pipe | ✅ works |
| `gaveta ls [type]` | Browse by category | ✅ works |
| `gaveta show <id>` · `rm <id>` · `export` | Inspect, remove, back up | ✅ works |
| `gaveta f "query"` | Semantic find (`-c` copies best hit to clipboard) | Stage 5 |
| `gaveta cred <name>` | Resolve a credential ref → vault → clipboard (auto-clear) | Stage 6 |
| `gaveta cred --new` | Create a vault entry + save its reference | Stage 6 |
| `gaveta ui` | Open the local web view | Stage 8 |

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

Contributions are welcome from day zero — but so are the rules, from day zero. They are
short, and they are non-negotiable: spec first, English everywhere, Conventional Commits,
tests with every PR, docs in the same PR, and security as a hard boundary (no code path may
ever return, log, or persist a secret value).

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR, and
[`CHANGELOG.md`](CHANGELOG.md) for what has landed.

By contributing you agree that your contributions are licensed under Apache 2.0.

## License

[Apache 2.0](LICENSE)
