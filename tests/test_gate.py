"""The secret gate as a pure function: scan classifies, redact rewrites.

These test `gate.scan` and `gate.redact` in isolation, without argv, a tty, or a
database. The ≥30-secret corpus and the benign set live in the shared fixtures module
so Stage 9's MCP redaction pass can reuse the exact fixtures (CLAUDE.md).
"""

import re

import pytest

from gaveta import gate
from gaveta.gate import Finding, Level, Verdict
from tests.fixtures.secret_corpus import (
    BENIGN_HIGH_ENTROPY,
    KNOWN_FORMAT_SECRETS,
    PLAIN_PROSE,
)

# --- the corpus: every known-format secret must block ------------------------


def test_the_corpus_has_at_least_thirty_known_format_secrets() -> None:
    """Guard on the guard: a shrunk corpus would make the 100%-blocked test vacuous."""
    assert len(KNOWN_FORMAT_SECRETS) >= 30


@pytest.mark.parametrize("secret", KNOWN_FORMAT_SECRETS, ids=lambda s: s[:24])
def test_every_known_format_secret_is_blocked(secret: str) -> None:
    """The hard assert. One miss fails the suite (CLAUDE.md, Stage 3 spec)."""
    assert gate.scan(secret).blocked, f"NOT blocked: {secret!r}"


# --- the benign set: suspicious at most, never blocked -----------------------


@pytest.mark.parametrize("benign", BENIGN_HIGH_ENTROPY, ids=lambda s: s[:24])
def test_benign_high_entropy_is_never_blocked(benign: str) -> None:
    """A git SHA or UUID may rate suspicious; it must never be blocked outright."""
    assert gate.scan(benign).level is not Level.blocked, f"blocked benign: {benign!r}"


@pytest.mark.parametrize("prose", PLAIN_PROSE, ids=lambda s: s[:24])
def test_plain_prose_is_clean(prose: str) -> None:
    """The zero-friction promise: ordinary notes produce no prompt and no block."""
    assert gate.scan(prose).level is Level.clean, f"not clean: {prose!r}"


# --- scan: the known-format tier, rule by rule -------------------------------


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("deploy key: AKIAIOSFODNN7EXAMPLE", "aws_access_key"),
        ("ghp_012345678901234567890123456789012345 is my token", "github_token"),
        ("xoxb-EXAMPLE-SLACK-BOT-TOKEN-NOT-REAL-000000", "slack_token"),
        # `sk_live_…` assembled so the literal never appears whole (see secret_corpus).
        ("sk" + "_live_" + "EXAMPLESTRIPEKEYNOTREAL000000", "stripe_secret_key"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private_key_pem"),
        ("postgres://admin:s3cr3tPass@db.example.com/app", "url_userinfo_password"),
        (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fw",
            "jwt",
        ),
    ],
)
def test_scan_blocks_and_names_the_rule(text: str, rule: str) -> None:
    verdict = gate.scan(text)
    assert verdict.blocked
    assert any(f.rule == rule for f in verdict.findings), (
        f"expected rule {rule!r} among {[f.rule for f in verdict.findings]}"
    )


def test_a_blocked_finding_carries_a_human_label() -> None:
    """The label is what the block message reads back to the user."""
    (finding,) = [
        f
        for f in gate.scan("key AKIAIOSFODNN7EXAMPLE").findings
        if f.rule == "aws_access_key"
    ]
    assert finding.label == "an AWS access key"
    # The span points at the key itself, not the surrounding text.
    assert (
        "AKIAIOSFODNN7EXAMPLE"
        in "key AKIAIOSFODNN7EXAMPLE"[finding.start : finding.end]
    )


# --- scan: the suspicious tier -----------------------------------------------


def test_a_context_word_beside_a_value_is_suspicious() -> None:
    """No known format, but `password:` in front makes it a judgment call."""
    verdict = gate.scan("password: MargaritaVerde2024!")
    assert verdict.suspicious
    assert any(f.rule.startswith("context_word:") for f in verdict.findings)


def test_a_spanish_context_word_is_recognized() -> None:
    """The list is bilingual on purpose — the user's captures mix languages."""
    assert gate.scan("clave: MargaritaVerde2024!").suspicious


def test_a_short_value_beside_a_context_word_is_not_flagged() -> None:
    """`pwd=x` is noise, not a secret. MIN_CONTEXT_VALUE_LEN guards it."""
    assert gate.scan("pwd=short").level is Level.clean


def test_a_long_random_token_is_suspicious() -> None:
    """base64 of random-ish bytes clears the entropy bar without a known format."""
    verdict = gate.scan("blob aGVsbG8gd29ybGQgc2VjcmV0IHZhbHVlIGhlcmU=")
    assert verdict.suspicious
    assert any(f.rule == "high_entropy" for f in verdict.findings)


def test_a_git_sha_stays_below_the_entropy_bar() -> None:
    """40-hex tops out ~3.9 bits/char; 4.0 sits just above it (ADR-003)."""
    assert gate.scan("e1c2f3a4b5c6d7e8f90112233445566778899aab").level is Level.clean


def test_a_short_high_entropy_token_is_not_flagged() -> None:
    """Below MIN_TOKEN_LEN, density alone does not trigger — short words would."""
    assert gate.scan("Zx9!qWmB").level is Level.clean


def test_empty_input_is_clean() -> None:
    """The degenerate case: nothing to scan, nothing flagged, entropy is 0."""
    assert gate.scan("").level is Level.clean
    assert gate._shannon_entropy("") == 0.0


# --- scan: precedence and structure ------------------------------------------


def test_known_format_wins_over_suspicious() -> None:
    """A JWT is also high-entropy; the verdict is blocked, not suspicious."""
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fw"
    assert gate.scan(jwt).level is Level.blocked


def test_scan_returns_a_frozen_verdict() -> None:
    verdict = gate.scan("clean text")
    assert isinstance(verdict, Verdict)
    with pytest.raises(AttributeError):
        verdict.level = Level.blocked  # type: ignore[misc]


# --- redact ------------------------------------------------------------------


def test_redact_replaces_the_secret_span() -> None:
    raw = "deploy key: AKIAIOSFODNN7EXAMPLE now"
    redacted = gate.redact(raw, gate.scan(raw))

    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert gate.REDACTED in redacted
    # Surrounding text survives.
    assert redacted.startswith("deploy key: ")
    assert redacted.endswith(" now")


def test_redact_of_a_clean_verdict_is_the_identity() -> None:
    """`--redact` on ordinary text (no findings) saves the text unchanged."""
    raw = "totally normal note about lunch"
    assert gate.redact(raw, gate.scan(raw)) == raw


def test_redact_handles_two_secrets_without_corrupting_offsets() -> None:
    """Right-to-left application keeps earlier spans valid as later ones shrink/grow."""
    raw = "a AKIAIOSFODNN7EXAMPLE b AKIAIOSFODNN7EXAMPLE c"
    redacted = gate.redact(raw, gate.scan(raw))

    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert redacted.count(gate.REDACTED) == 2
    assert redacted == f"a {gate.REDACTED} b {gate.REDACTED} c"


def test_redact_coalesces_overlapping_findings() -> None:
    """A span matched by two rules (JWT + high-entropy) is replaced once, not twice."""
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fw"
    redacted = gate.redact(jwt, gate.scan(jwt))

    assert redacted == gate.REDACTED  # exactly one replacement over the whole token


def test_redact_uses_only_the_spans_it_was_handed() -> None:
    """redact operates on the verdict passed in — no second scan of its own."""
    raw = "xxAKIAIOSFODNN7EXAMPLExx"
    hand_made = Verdict(level=Level.blocked, findings=(Finding("manual", 2, 22, "x"),))

    assert gate.redact(raw, hand_made) == f"xx{gate.REDACTED}xx"


# --- the seam contract used by core.capture ----------------------------------


def test_verdict_blocked_and_suspicious_are_mutually_exclusive() -> None:
    for text in ("clean", "password: MargaritaVerde2024!", "AKIAIOSFODNN7EXAMPLE"):
        verdict = gate.scan(text)
        assert not (verdict.blocked and verdict.suspicious)


def test_no_finding_span_is_out_of_range() -> None:
    """Every span must index into the text it came from — redact depends on it."""
    for text in (*KNOWN_FORMAT_SECRETS, "password: MargaritaVerde2024!"):
        for finding in gate.scan(text).findings:
            assert 0 <= finding.start < finding.end <= len(text)
            assert re.search(r"\S", text[finding.start : finding.end])
