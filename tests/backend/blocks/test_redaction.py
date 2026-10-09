import json

from writer.blocks.redaction import (
    REDACTED,
    collect_secret_values,
    is_sensitive_header,
    redact_body,
    redact_headers,
    redact_text,
    redact_url,
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


def test_collect_secret_values_uses_block_resolution():
    context = {"$TOKEN": "context-token", "vault": {"K": "vault-value"}}

    def resolve(expr):
        if expr in context:
            return context[expr]
        return context["vault"].get(expr.split(".", 1)[1])

    secrets = collect_secret_values(None, ["@{$TOKEN}", "x @{vault.K}", "@{state_value}"], resolve)
    assert set(secrets) == {"context-token", "vault-value"}


def test_redact_url_handles_alternate_encodings():
    secret = "a/b+c d"
    for url in (
        "https://x.test/?k=a/b%2Bc%20d",
        "https://x.test/?k=a%2fb%2bc+d",
        "https://x.test/?k=a/b+c d",
    ):
        assert secret not in redact_url(url, [secret]).replace("%20", " ")
        assert REDACTED in redact_url(url, [secret])
    assert redact_url("https://x.test/?q=a%2Fb", ["unrelated"]) == "https://x.test/?q=a%2Fb"


def test_redact_body_keeps_json_valid():
    body = '{"flag": true, "pin": 123456, "token": "Bearer secret-value", "n": null}'
    redacted = redact_body(body, ["true", "123456", "secret-value"])
    assert json.loads(redacted) == {
        "flag": REDACTED,
        "pin": REDACTED,
        "token": "Bearer " + REDACTED,
        "n": None,
    }
    assert redact_body(body, ["unrelated"]) == body
    assert redact_body("plain secret-value text", ["secret-value"]) == "plain " + REDACTED + " text"
