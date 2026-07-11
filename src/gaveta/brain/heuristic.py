"""The heuristic floor — classification without a model.

This is what runs when Ollama is absent, slow, or broken, and it is deliberately dumb:
three rules, no I/O, fully deterministic, so a capture is never lost to a missing model.
`retag` upgrades a heuristically-classified item once the model is available.

The rules, in order:

1. **A lone URL → `link`**, with the URL as `content` and a readable title from it.
2. **Text with a URL among prose → `link`**, with the extracted URL as `content`.
3. **Shell-ish text → `command`**, with the command line as `content`.
4. **Everything else → `note`**, `content = None` — prose has no bare payload.

Content extraction is intentionally conservative: only the trivially-extractable payload
(a URL, a recognizable command) becomes `content`. Pulling a clean snippet out of
free-form narrative is the model's job, not a regex's, so the heuristic leaves `content`
null rather than guess wrong.
"""

import re

from gaveta.brain.types import Classification
from gaveta.db.models import ItemType

# A URL: http(s)/ftp scheme, host, optional path. Kept simple on purpose — this is
# classification, not validation. Anchored nowhere so it can be *found* inside prose.
_URL_RE = re.compile(r"(?:https?|ftp)://[^\s<>\"']+", re.IGNORECASE)

# Tokens that mark text as a shell command when they lead it: a `$` prompt, `sudo`, or a
# common binary. Matched at the start (after optional `$ `), so prose that just mentions
# "git" mid-sentence does not become a command.
_COMMAND_LEADERS = (
    "sudo",
    "git",
    "docker",
    "kubectl",
    "ssh",
    "scp",
    "curl",
    "wget",
    "npm",
    "yarn",
    "pnpm",
    "uv",
    "pip",
    "python",
    "python3",
    "node",
    "cargo",
    "make",
    "bash",
    "sh",
    "cd",
    "ls",
    "cat",
    "grep",
    "sed",
    "awk",
    "rm",
    "cp",
    "mv",
    "mkdir",
    "export",
    "psql",
    "mysql",
    "systemctl",
    "brew",
    "apt",
    "terraform",
    "aws",
    "gcloud",
)
_COMMAND_LEAD_RE = re.compile(
    r"^\s*\$?\s*(" + "|".join(re.escape(w) for w in _COMMAND_LEADERS) + r")\b"
)

# Title length cap — a label, not the whole note. Matches the DB's title column bound.
_TITLE_MAX = 80


def _shorten(text: str, limit: int = _TITLE_MAX) -> str:
    """One line, collapsed whitespace, an ellipsis if it ran long."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _title_from_url(url: str) -> str:
    """A readable label for a link: host + first path segment, if any."""
    stripped = re.sub(r"^(?:https?|ftp)://", "", url, flags=re.IGNORECASE)
    return _shorten(stripped.rstrip("/"))


class HeuristicClassifier:
    """Deterministic classification: no model, no network, never raises."""

    def classify(self, text: str) -> Classification:
        stripped = text.strip()
        urls = _URL_RE.findall(stripped)

        # A lone URL: the whole capture is one link.
        if len(urls) == 1 and urls[0] == stripped:
            return Classification(
                type=ItemType.link,
                title=_title_from_url(urls[0]),
                content=urls[0],
            )

        # A URL living inside prose: still a link, content is the bare URL.
        if urls:
            return Classification(
                type=ItemType.link,
                title=_shorten(stripped),
                content=urls[0],
            )

        # Shell-ish text: a command, content is the command line itself.
        if _COMMAND_LEAD_RE.match(stripped):
            command = _shorten(stripped, limit=10_000)
            return Classification(
                type=ItemType.command,
                title=_shorten(stripped),
                content=command,
            )

        # Everything else is a note. Prose has no bare payload, so content is null.
        return Classification(
            type=ItemType.note,
            title=_shorten(stripped) if stripped else None,
            content=None,
        )
