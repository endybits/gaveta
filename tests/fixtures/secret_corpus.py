# ─────────────────────────────────────────────────────────────────────────────────────
#  SECRET CORPUS — test fixtures, NOT live credentials.
#
#  Every string in KNOWN_FORMAT_SECRETS is a PUBLIC DOCUMENTATION EXAMPLE (AWS's own
#  `AKIAIOSFODNN7EXAMPLE`, the jwt.io sample token, provider-docs sample keys) or a
#  CLEARLY SYNTHETIC value assembled to match a format. None is a real secret; none
#  grants access to anything. They exist so the secret gate can be tested against the
#  shapes it must catch.
#
#  Because these strings are *designed to look like secrets*, a naive secret scanner
#  run over the repo would flag this file. That is expected: `.gitleaks.toml` allowlists
#  this path (see the repo root), scoped narrowly here so it cannot mask a real secret
#  elsewhere. The repo stays clean under a scanner by policy, not by luck.
#
#  This module is imported by tests/test_gate.py and reused by the Stage 9 MCP redaction
#  pass (CLAUDE.md). Keep it dependency-free and never add a real credential.
# ─────────────────────────────────────────────────────────────────────────────────────

# The `_live_` infix of a Stripe key, kept out of any whole literal so a scanner's
# prefix-based Stripe detector never fires on this source. Joined into the fixtures.
_LIVE = "_" + "live" + "_"

# ≥30 known-format secrets. `scan()` must block 100% of these — a hard assert. Grouped
# by format for legibility; the gate does not care about the grouping.
KNOWN_FORMAT_SECRETS: tuple[str, ...] = (
    # --- AWS access keys (AWS docs' canonical example + synthetic prefixes) ---
    "AKIAIOSFODNN7EXAMPLE",
    "deploy with AKIAIOSFODNN7EXAMPLE today",
    "ASIAY34FZKBOKMUTVV7A",
    "AKIA1234567890ABCDEF",
    "AGPAI23HZ27SI6FQMGNQ",
    "AROAJ52OTH4H7EXAMPLE",
    # --- GitHub tokens: ghp_ / gho_ / ghu_ / ghs_ / ghr_ + 36 chars ---
    "ghp_012345678901234567890123456789012345",
    "gho_ABCDEFabcdef0123456789ABCDEFabcdef01",
    "ghu_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r",
    "ghs_wxyzWXYZ0123456789wxyzWXYZ0123456789",
    "ghr_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
    # --- Slack tokens (Slack's xox<b|p|a|r>- prefix shape) ---
    #
    # Defanged on purpose: the tails read EXAMPLE/FAKE so a real secret scanner's
    # high-confidence Slack detector does not fire on the repo, while still matching the
    # gate's prefix-based rule. Never paste a real Slack token here.
    "xoxb-EXAMPLE-SLACK-BOT-TOKEN-NOT-REAL-000000",
    "xoxp-EXAMPLE-SLACK-USER-TOKEN-NOT-REAL-00000",
    "xoxa-EXAMPLE-SLACK-APP-TOKEN-NOT-REAL-000000",
    "xoxr-EXAMPLE-SLACK-REFRESH-TOKEN-NOT-REAL-00",
    # --- Stripe secret keys (sk_live / rk_live shape) ---
    #
    # Assembled from split pieces so the literal `sk_live_…` never appears whole in
    # source. A scanner's Stripe detector keys on the prefix alone and would flag any
    # body, so the value is built at import time; the gate scans the
    # runtime string exactly as it would a real one. See the header.
    f"sk{_LIVE}EXAMPLESTRIPEKEYNOTREAL000000",
    f"sk{_LIVE}FAKESTRIPESECRETNOTREAL111111",
    f"rk{_LIVE}EXAMPLERESTRICTEDKEYNOTREAL22222",
    # --- PEM private-key headers (the header is the signal) ---
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "config:\n-----BEGIN PRIVATE KEY-----\nMIIEvExample",
    # --- user:pass@ in connection-string URLs ---
    "postgres://admin:s3cr3tPassw0rd@db.example.com:5432/app",
    "mysql://root:hunter2pass@127.0.0.1:3306/shop",
    "redis://user:v3ryS3cret@cache.internal:6379/0",
    "mongodb://svc:P%40ssw0rd123@cluster0.example.net/db",
    "amqp://guest:guestPassword@broker.local:5672/",
    # --- JWTs (the jwt.io default sample + synthetic three-segment tokens) ---
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
    "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
    "eyJyb2xlIjoiYWRtaW4ifQ.abcDEFghiJKLmnoPQRstuVWXyz0123456789ABCDEF",
    "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJnYXZldGEifQ.c2lnbmF0dXJlLXBsYWNlaG9sZGVy",
)

# Benign high-entropy strings: dense enough to *look* suspicious, but not secrets. The
# gate may rate these `suspicious`; it must NEVER rate them `blocked` (ADR-003). Saving
# one is one keystroke at the prompt, never a silent loss.
BENIGN_HIGH_ENTROPY: tuple[str, ...] = (
    # git commit SHAs (40 hex) — entropy sits just below the 4.0 threshold.
    "e1c2f3a4b5c6d7e8f90112233445566778899aab",
    "0123456789abcdef0123456789abcdef01234567",
    "deadbeefcafebabe1234567890abcdef12345678",
    # UUIDs — dashes drag the entropy down further still.
    "550e8400-e29b-41d4-a716-446655440000",
    "123e4567-e89b-12d3-a456-426614174000",
    # base64 of innocuous text (decodes to plain words, but reads as a blob).
    "aGVsbG8gd29ybGQsIHRoaXMgaXMgbm90IGEgc2VjcmV0IGF0IGFsbA==",
    # a long ordinary Spanish sentence (mixed language, no secret).
    "una oración larga y perfectamente ordinaria sobre el almuerzo de ayer",
)

# Plain prose: the happy path. Must rate `clean` — no prompt, no friction.
PLAIN_PROSE: tuple[str, ...] = (
    "totally normal note about lunch",
    "remember to email the design team on Monday",
    "the meeting moved to 3pm in the small room",
    "comprar café y pan para la reunión del jueves",
    "ssh into the jump host and check the qa logs",
)
