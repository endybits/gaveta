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

☝️ That is the destination. **What actually runs today** is the Stage 1 walking
skeleton — see [What works right now](#what-works-right-now).

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

**Stage 1 — simulated capture. Persistence lands in Stage 2.** Gaveta accepts your text
and prints exactly what it *would* save. Nothing is written to disk, no model runs, and
there are no side effects beyond stdout.

```
$ gaveta "ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database"
[gaveta] would save:
  raw      : ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database
  type     : unknown   (classification lands in Stage 4)
  tags     : []
  captured : 2026-07-09T14:03:11-05:00
  source   : cli
```

Pipe it instead, with `-` or on its own — the two are equivalent:

```
$ echo "remember this" | gaveta -
$ pbpaste | gaveta
```

`--json` emits the machine view: one JSON object per capture, on one line. This schema is
the contract every later stage honors, and it is snapshot-tested, so it cannot drift by
accident.

```
$ gaveta "x" --json
{"raw":"x","source":"cli","captured_at":"2026-07-09T14:03:11-05:00","type":"unknown","tags":[]}
```

Three things worth knowing:

- **`gv` is an alias for `gaveta`.** Both commands are installed and point at the same
  entry point, so `gv "some text"` is the capture path with less typing.
- **Reserved words.** `ls`, `show`, `rm`, `export`, `retag`, `f`, `reindex`, `cred`,
  `daemon`, and `ui` are reserved for the stages that implement them. `gaveta ls` exits
  with a message naming its stage rather than capturing the word "ls". To capture one as
  text, use `gaveta -- "ls"`.
- **Text starting with a dash.** A bare `-L` looks like an option to any argument parser.
  Quoted text with a space (`gaveta "ssh -L 5432"`) is fine; a lone dash token needs
  `gaveta -- "-L"`, or pipe it in.

Empty input (no argument, nothing piped) prints usage and exits `2`.

## Basic commands (target CLI)

Not yet implemented — this is the destination, not today's behavior. See
[What works right now](#what-works-right-now) for Stage 1.

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

Contributions are welcome from day zero — but so are the rules, from day zero. They are
short, and they are non-negotiable: spec first, English everywhere, Conventional Commits,
tests with every PR, docs in the same PR, and security as a hard boundary (no code path may
ever return, log, or persist a secret value).

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR, and
[`CHANGELOG.md`](CHANGELOG.md) for what has landed.

By contributing you agree that your contributions are licensed under Apache 2.0.

## License

[Apache 2.0](LICENSE)
