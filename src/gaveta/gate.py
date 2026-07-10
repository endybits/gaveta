"""The secret gate — layer 1 (deterministic detection) of the four-layer defense.

`scan(raw) -> Verdict` runs at the very front of the capture pipeline, before anything
is persisted and, from Stage 4 on, before any model sees the text. It is pure core: it
knows nothing of argv, a terminal, or an exit code. The CLI decides how a verdict is
rendered, whether to prompt, and what to return to the shell; this module only decides
*what the text is*.

Two tiers:

- **Known formats → `blocked`.** Regexes for credential shapes that are unambiguous:
  AWS keys, GitHub/Slack/Stripe tokens, PEM private-key headers, `user:pass@` URLs,
  JWTs. A match here is not a judgment call, so it is refused outright (the CLI turns
  that into exit 3 and a message pointing at the vault flow).
- **Entropy / context words → `suspicious`.** A long high-entropy token, or a value
  sitting next to a word like `password`/`clave`, is *maybe* a secret. That is a
  judgment call, so it never blocks on its own — it raises `suspicious`, and the human
  gets the `[v/r/s]` confirmation (or, under a pipe, a block with an escape hatch).

`redact(raw, verdict)` replaces exactly the spans the same scan found with `[REDACTED]`.
One scan, one set of spans: detection, redaction, and the block message cannot drift.

The honest limit, stated in docs/security-model.md and worth repeating here: no format
detector has 100% recall. `MargaritaVerde2024!` is a real password with no format — the
context-word tier is what gives even that a chance, and containment (layer 4, the
local-first architecture) is what covers what leaks. See ADR-003.
"""

import enum
import math
import re
from dataclasses import dataclass

# ── The suspicious-tier thresholds. Named, not buried in a function. ──────────────────
#
# 4.0 bits/char sits deliberately at the git-SHA boundary: 16-symbol hex tops out at
# exactly 4.0, so a 40-hex SHA or a UUID rates at or just below the line — suspicious at
# worst, never blocked — while base64 of random bytes (~5.5-6.0) clears it. See ADR-003.
ENTROPY_THRESHOLD = 4.0
# Below this length, ordinary long words can spuriously clear the entropy bar; 20 keeps
# them out while still catching real tokens (API keys, base64 blobs).
MIN_TOKEN_LEN = 20
# A context word only flags a value with some substance behind it: `pwd=x` is noise.
MIN_CONTEXT_VALUE_LEN = 8

# Words that, sitting next to a value, mark it as probably-a-secret. Bilingual on
# purpose — the user's captures mix English and Spanish — and maintained by editing this
# frozenset (no config file this stage; that is Stage 4+). Order does not matter.
CONTEXT_WORDS: frozenset[str] = frozenset(
    {
        # English
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "auth",
        "bearer",
        # Spanish
        "clave",
        "contraseña",
        "secreto",
        "credencial",
    }
)

REDACTED = "[REDACTED]"


class Level(enum.Enum):
    """How the gate judged the input. Ordered by severity for `max()`."""

    clean = "clean"
    suspicious = "suspicious"
    blocked = "blocked"


@dataclass(frozen=True)
class Finding:
    """One match: what rule fired, where in `raw`, and how to name it to a human."""

    rule: str
    start: int
    end: int
    label: str


@dataclass(frozen=True)
class Verdict:
    """The scan result. Internal — it never crosses the `--json` wire (ADR-003)."""

    level: Level
    findings: tuple[Finding, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.level is Level.blocked

    @property
    def suspicious(self) -> bool:
        return self.level is Level.suspicious


# ── Known-format rules → blocked ──────────────────────────────────────────────────────
#
# Patterns are borrowed in shape (not code) from gitleaks/trufflehog. Each entry is a
# compiled regex and the human phrase the block message uses. The phrase completes
# "...what looks like <label>".


@dataclass(frozen=True)
class _Rule:
    name: str
    pattern: re.Pattern[str]
    label: str


_KNOWN_FORMAT_RULES: tuple[_Rule, ...] = (
    _Rule(
        "aws_access_key",
        # AKIA (long-term) / ASIA (temporary) / others, then 16 base32 chars.
        re.compile(
            r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ABIA|ACCA)[A-Z0-9]{16}\b"
        ),
        "an AWS access key",
    ),
    _Rule(
        "github_token",
        # ghp_ (PAT), gho_ (OAuth), ghu_/ghs_ (app), ghr_ (refresh): prefix + 36 chars.
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"),
        "a GitHub token",
    ),
    _Rule(
        "slack_token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        "a Slack token",
    ),
    _Rule(
        "stripe_secret_key",
        # sk_live / rk_live (restricted). Test keys (sk_test) are not secrets to guard.
        re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b"),
        "a Stripe secret key",
    ),
    _Rule(
        "private_key_pem",
        re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
        "a private key (PEM block)",
    ),
    _Rule(
        "url_userinfo_password",
        # scheme://user:pass@host — the password in a connection string. Require a
        # non-trivial password so `http://user:@host` and bare `a:b@` in prose miss.
        re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@]+:[^\s:/@]{3,}@[^\s/]+"),
        "a password in a connection-string URL",
    ),
    _Rule(
        "jwt",
        # Three base64url segments; the first (header) begins eyJ ({"...) in practice.
        re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
        "a JSON Web Token (JWT)",
    ),
)

# A value token: a run of non-whitespace, non-quote characters. Used to isolate the
# thing a context word points at, and to scan for high-entropy blobs.
_TOKEN = re.compile(r"[^\s\"'`]+")

# `word: value` / `word = value` / `word=value`. The word is captured case-insensitively
# and checked against CONTEXT_WORDS; the value is the first token after the separator.
_CONTEXT = re.compile(
    r"(?P<word>[A-Za-zÀ-ÿ_]+)\s*[:=]\s*(?P<value>[^\s\"'`]+)",
)


def _shannon_entropy(text: str) -> float:
    """Bits per character. 0 for the empty string; maxes at log2(len(alphabet))."""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    length = len(text)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _known_format_findings(raw: str) -> list[Finding]:
    """Every known-format match in `raw`. Empty when none fire."""
    findings: list[Finding] = []
    for rule in _KNOWN_FORMAT_RULES:
        for match in rule.pattern.finditer(raw):
            findings.append(Finding(rule.name, match.start(), match.end(), rule.label))
    return findings


def _suspicious_findings(raw: str) -> list[Finding]:
    """High-entropy tokens and context-word values. Empty when nothing looks off."""
    findings: list[Finding] = []

    # High-entropy tokens: long enough, and dense enough to not be prose.
    for match in _TOKEN.finditer(raw):
        token = match.group()
        if len(token) >= MIN_TOKEN_LEN and _shannon_entropy(token) >= ENTROPY_THRESHOLD:
            findings.append(
                Finding(
                    "high_entropy",
                    match.start(),
                    match.end(),
                    "a high-entropy value that may be a secret",
                )
            )

    # Context words pointing at a substantial value.
    for match in _CONTEXT.finditer(raw):
        if match.group("word").lower() not in CONTEXT_WORDS:
            continue
        value = match.group("value")
        if len(value) < MIN_CONTEXT_VALUE_LEN:
            continue
        start, end = match.span("value")
        findings.append(
            Finding(
                f"context_word:{match.group('word').lower()}",
                start,
                end,
                "a value next to a password-like keyword",
            )
        )

    return findings


def scan(raw: str) -> Verdict:
    """Judge `raw` before anything else touches it.

    `blocked` if any known-format rule fires; otherwise `suspicious` if the entropy or
    context-word tier fires; otherwise `clean`. Known-format findings take precedence,
    but suspicious findings are still carried when present, so a caller that chooses to
    redact a blocked capture redacts every located span, not just the formatted ones.
    """
    known = _known_format_findings(raw)
    suspicious = _suspicious_findings(raw)
    findings = tuple(known + suspicious)

    if known:
        level = Level.blocked
    elif suspicious:
        level = Level.suspicious
    else:
        level = Level.clean

    return Verdict(level=level, findings=findings)


def redact(raw: str, verdict: Verdict) -> str:
    """Replace each finding's span in `raw` with `[REDACTED]`.

    Applied right-to-left so that replacing a later span cannot shift the offsets of an
    earlier one. Overlapping spans (a token that is both high-entropy and format-known)
    are coalesced, so a region is never replaced twice. A verdict with no findings — a
    `clean` capture the caller redacted anyway — returns `raw` unchanged: redacting zero
    spans is the identity.
    """
    if not verdict.findings:
        return raw

    # Sort by start, then merge overlaps into disjoint (start, end) regions.
    spans = sorted((f.start, f.end) for f in verdict.findings)
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    result = raw
    for start, end in reversed(merged):
        result = result[:start] + REDACTED + result[end:]
    return result
