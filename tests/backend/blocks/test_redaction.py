from writer.blocks.redaction import (
    REDACTED,
    collect_secret_values,
    is_sensitive_header,
    redact_headers,
    redact_text,
)


def test_is_sensitive_header():
    for name in (
        "Authorization",
        "proxy-authorization",
        "Cookie",
        "X-API-Key",
        "X-Goog-Api-Key",
        "X-Auth-Token",
        "x-amz-security-token",
        "X-Client-Secret",
    ):
        assert is_sensitive_header(name), name
    for name in ("Content-Type", "Accept", "User-Agent", "Host", "Content-Length"):
        assert not is_sensitive_header(name), name


def test_collect_secret_values(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "env-token-value")
    monkeypatch.setenv("UNUSED_TOKEN", "unused-value")
    secrets = collect_secret_values(
        {"A": "short-but-ok", "B": {"nested": "nested-secret"}, "C": "abc", "D": True},
        ['{"X": "@{$MY_TOKEN}"}', r"\@{$UNUSED_TOKEN}", None],
    )
    assert set(secrets) == {"short-but-ok", "nested-secret", "env-token-value"}
    assert collect_secret_values(None, []) == []


def test_redact_text_covers_encoded_variants():
    secret = 'p@ss word/"x"'
    assert redact_text("raw " + secret, [secret]) == "raw " + REDACTED
    assert redact_text("q=p%40ss%20word%2F%22x%22", [secret]) == "q=" + REDACTED
    assert redact_text("q=p%40ss+word%2F%22x%22", [secret]) == "q=" + REDACTED
    assert redact_text('{"t": "p@ss word/\\"x\\""}', [secret]) == '{"t": "' + REDACTED + '"}'
    assert redact_text(None, [secret]) is None


def test_redact_headers():
    headers = {"Authorization": "Bearer x", "X-Custom": "id-secret-value", "Accept": "*/*"}
    assert redact_headers(headers, ["secret-value"]) == {
        "Authorization": REDACTED,
        "X-Custom": "id-" + REDACTED,
        "Accept": "*/*",
    }
