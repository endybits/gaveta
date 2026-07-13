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
✓ saved · id 7 · command · ssh, rds, qa

$ gaveta f "how did I connect to the qa database?"
1. [command] SSH tunnel to qa RDS   →  gaveta show 42 · -c to copy
```

☝️ That is the destination, and as of Stage 5 most of it runs. **What actually runs today**
captures, classifies (with a local model), lists, shows, reclassifies, removes, exports, and
**finds by meaning** (`gaveta f`, with `-c` to copy the best hit) — see
[What works right now](#what-works-right-now).

## Security model (read this first)

**Secrets never enter Gaveta.** A deterministic secret gate scans every capture
*before* anything else — including any model — sees it. Passwords, API keys, and
tokens are rejected on sight, and pointed toward your real vault (Bitwarden or
KeePassXC — the vault flow itself lands in a later release). The eventual design
stores only *references*; resolving one sends the secret straight from the vault to
your clipboard, never through Gaveta's storage, logs, or model context.

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

**Stage 5 — semantic retrieval.** Captures are stored in a local SQLite database at
`~/.gaveta/gaveta.db`, the deterministic secret gate scans every capture before it is
written, a local model classifies each capture — its type (`link` / `command` / `note`), a
title, tags, and the clean copyable `content` — and **`gaveta f "query"` finds items by
meaning**. No Ollama? Gaveta degrades to heuristics and never blocks a capture; `gaveta
retag <id>` upgrades it later.

```
$ gaveta "ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database"
✓ saved · id 1 · command · ssh, rds, qa

$ gaveta ls
     1  command         SSH tunnel to qa database  · ssh, rds, qa

$ gaveta show 1
  id      : 1
  raw     : ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database
  type    : command
  title   : SSH tunnel to qa database
  content : ssh -L 5432:rds-qa:5432 jump-host
  tags    : ssh, rds, qa
  created : 2026-07-11T09:14:03-05:00
  updated : 2026-07-11T09:14:03-05:00
```

The three layers: `raw` is everything you typed, `content` is the copyable part
(the bare command here), `title` is the readable label. `content` is null for plain prose.
Ran the capture before Ollama was up? `gaveta retag 1` re-classifies it in place.

**Find it back by meaning.** `gaveta reindex` embeds the drawer; `gaveta f "query"` returns
the closest hits, and `-c` copies the best hit's payload straight to your clipboard:

```
$ gaveta reindex
✓ reindexed · embedded 1 of 1

$ gaveta f "how did I reach the qa database?"
     1  command         SSH tunnel to qa database

$ gaveta f "qa tunnel" -c
✓ copied to clipboard · ssh -L 5432:rds-qa:5432 jump-host
```

Ranking is hybrid — keyword (FTS5) fused with vector similarity — and it degrades honestly:
where the `sqlite-vec` extension cannot load (common on Homebrew/pyenv Pythons) or Ollama is
absent, `f` runs **keyword-only** and says so on stderr, never crashing. A freshly captured
item is keyword-searchable at once and semantically searchable after the next `reindex`. See
[docs/search.md](docs/search.md) for the ranking, honestly.

Pipe it instead, with `-` or on its own — the two are equivalent:

```
$ echo "remember this" | gaveta -
$ pbpaste | gaveta
```

`--json` returns the saved item — id included — as one JSON object. This is the machine
contract every later stage honors, and it is snapshot-tested, so it cannot drift by
accident. `created_at` is UTC (`Z`); the human views show your local time.

```
$ gaveta "https://sqlite.org/withoutrowid.html" --json
{"id":2,"raw":"https://sqlite.org/withoutrowid.html","type":"link","title":"sqlite.org/withoutrowid.html","content":"https://sqlite.org/withoutrowid.html","tags":[],"created_at":"2026-07-11T14:14:03.482Z","updated_at":"2026-07-11T14:14:03.482Z"}
```

**The secret gate.** A known-format secret — an AWS key, a GitHub/Slack/Stripe token, a
PEM private key, a `user:pass@` URL, a JWT — is rejected before anything is written, with
exit code `3`:

```
$ gaveta "deploy key: AKIAIOSFODNN7EXAMPLE"
✋ blocked: input contains what looks like an AWS access key.
   Secrets never enter Gaveta. Store it in your vault and save a reference
   instead — that flow lands in a later release (gaveta cred --new).
   To keep this capture now with the secret masked:  gaveta --redact
```

A value that only *looks* risky — high entropy, or sitting next to a word like `password:`
or `clave:` — prompts you at a terminal (`[v]ault · [r]edact · [s]ave anyway`). Over a pipe,
where there is no terminal to ask, it blocks rather than guess. `--redact` masks the
detected part with `[REDACTED]` and saves the rest, from any source:

```
$ gaveta --redact "deploy key: AKIAIOSFODNN7EXAMPLE"
✓ saved · id 3 · note · redacted
```

Full details, honest limits, and the four-layer design are in
[`docs/security-model.md`](docs/security-model.md).

Manage what you have captured:

| Command | What it does |
|---|---|
| `gaveta ls [type]` | List captures, newest first; optionally filter by type |
| `gaveta show <id>` | Show one capture in full |
| `gaveta retag <id>` | Re-classify a capture (type/title/tags/content) |
| `gaveta rm <id>` | Remove one (idempotent — a second `rm` of the same id is fine) |
| `gaveta export` | Dump every capture as a JSON array to stdout |

`gaveta export > backup.json` is the backup story; redirection is the file, so there is no
`--output` flag. **Deleting `~/.gaveta/gaveta.db` resets the world** — the next command
re-creates it, empty. Full schema in [`docs/data-model.md`](docs/data-model.md).

Three things worth knowing:

- **`gv` is an alias for `gaveta`.** Both commands are installed and point at the same
  entry point, so `gv ls` and `gv "some text"` work with less typing.
- **Reserved words.** `cred`, `daemon`, and `ui` are reserved for the stages that implement
  them; `gaveta cred x` exits with a message naming its stage rather than capturing "cred".
  To capture a reserved word as text, use `gaveta -- "cred"`. (`f` and `reindex` are live as
  of Stage 5.)
- **Text starting with a dash.** A bare `-L` looks like an option to any argument parser.
  Quoted text with a space (`gaveta "ssh -L 5432"`) is fine; a lone dash token needs
  `gaveta -- "-L"`, or pipe it in.

Exit codes: `0` success · `1` not found (`show` of a missing id) · `2` usage (empty input,
a reserved word, a parse error) · `3` a blocked secret. A script can tell "nothing to
capture" from "that was a secret, and it was not saved."

## Basic commands (target CLI)

The rest of the destination, not yet implemented. See
[What works right now](#what-works-right-now) for what runs today.

| Command | What it does | Status |
|---|---|---|
| `gaveta "some text"` | Capture anything — classification is automatic | ✅ works |
| `echo "..." \| gaveta -` | Capture from stdin / clipboard pipe | ✅ works |
| `gaveta ls [type]` | Browse by category | ✅ works |
| `gaveta show <id>` · `retag <id>` · `rm <id>` · `export` | Inspect, reclassify, remove, back up | ✅ works |
| `gaveta f "query"` | Semantic find (`-c` copies best hit to clipboard) | ✅ works |
| `gaveta reindex` | Backfill embeddings for the drawer | ✅ works |
| `gaveta cred <name>` | Resolve a credential ref → vault → clipboard (auto-clear) | Stage 6 |
| `gaveta cred --new` | Create a vault entry + save its reference | Stage 6 |
| `gaveta ui` | Open the local web view | Stage 8 |

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) — **optional but recommended.** It powers classification
  (and, from Stage 5, semantic search). Without it, Gaveta degrades to simple heuristics
  and never blocks a capture. To enable it, install Ollama and pull the default model:

  ```bash
  ollama pull qwen2.5:3b-instruct   # classification
  ollama pull nomic-embed-text      # semantic search (gaveta f)
  ```

- Bitwarden CLI (`bw`) or KeePassXC (`keepassxc-cli`) for the credentials flow (optional)

### Configuration

Gaveta reads an optional `~/.gaveta/config.toml` (honoring `GAVETA_HOME`). Absent, it uses
the defaults below; a malformed file, or an endpoint that is not localhost, is a usage
error (exit `2`). Gaveta never talks to a non-local model.

```toml
[model]
name            = "qwen2.5:3b-instruct"  # classification model (any you have pulled)
embedding_model = "nomic-embed-text"     # semantic-search model for `gaveta f`
endpoint        = "http://localhost:11434"  # must be localhost
timeout         = 2.5                    # seconds; a slower answer falls back to heuristics
```

Classification runs synchronously at capture with that hard timeout: if the model cannot
answer in time, Gaveta saves with heuristics and you can `gaveta retag <id>` later. Changing
`embedding_model` means the stored vectors no longer match, so it is a full `gaveta reindex`
(and a model whose vectors are a different width is refused rather than stored).

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
