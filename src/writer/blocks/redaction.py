"""
Helpers for keeping resolved secrets out of block results and request logs.
"""

import json
import os
import re
from typing import Any, Callable, Iterable, List, Mapping, Optional, Set
from urllib.parse import quote, quote_plus, unquote, unquote_plus

REDACTED = "[REDACTED]"

# Shorter values are too likely to collide with ordinary text.
MIN_SECRET_LENGTH = 4

SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "apikey",
        "x-auth-token",
        "x-access-token",
        "x-csrf-token",
        "x-xsrf-token",
    }
)

_SENSITIVE_HEADER_PATTERN = re.compile(
    r"auth|token|secret|passw|api[-_]?key|cookie|session|signature|credential",
    re.IGNORECASE,
)

_TEMPLATE_REGEX = re.compile(r"(?<!\\)@{([^{]*?)}")


def is_sensitive_header(name: str) -> bool:
    lowered = name.lower()
    return lowered in SENSITIVE_HEADER_NAMES or bool(_SENSITIVE_HEADER_PATTERN.search(lowered))


def _collect_strings(value: Any, into: Set[str]) -> None:
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_strings(item, into)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _collect_strings(item, into)
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        into.add(str(value))


def _env_lookup(expr: str) -> Any:
    return os.getenv(expr[1:])


def collect_secret_values(
    vault: Optional[Any] = None,
    field_templates: Iterable[Any] = (),
    resolve: Callable[[str], Any] = _env_lookup,
) -> List[str]:
    """
    Returns the plaintext values that must never be echoed: every vault
    secret, plus the resolved value of every ``@{$NAME}`` / ``@{vault.*}``
    expression in the given raw field templates. ``resolve`` evaluates an
    expression the same way the block does. Longest first, so overlapping
    secrets are replaced whole.
    """
    secrets: Set[str] = set()
    if vault:
        _collect_strings(vault, secrets)
    for template in field_templates:
        if not isinstance(template, str):
            continue
        for match in _TEMPLATE_REGEX.finditer(template):
            expr = match.group(1).strip()
            if not (expr.startswith("$") or expr.startswith("vault.")):
                continue
            try:
                value = resolve(expr)
            except Exception:
                value = _env_lookup(expr) if expr.startswith("$") else None
            if value is not None:
                _collect_strings(value, secrets)
    return sorted((s for s in secrets if len(s) >= MIN_SECRET_LENGTH), key=len, reverse=True)


def _variants(secret: str) -> List[str]:
    variants = {
        secret,
        quote(secret, safe=""),
        quote_plus(secret, safe=""),
        json.dumps(secret)[1:-1],
    }
    return sorted(variants, key=len, reverse=True)


def redact_text(text: Optional[str], secrets: Iterable[str]) -> Optional[str]:
    if not text:
        return text
    for secret in secrets:
        for variant in _variants(secret):
            if variant in text:
                text = text.replace(variant, REDACTED)
    return text


def redact_headers(headers: Mapping[str, Any], secrets: Iterable[str] = ()) -> dict:
    secrets = list(secrets)
    redacted = {}
    for name, value in headers.items():
        if is_sensitive_header(name):
            redacted[name] = REDACTED
        else:
            redacted[name] = redact_text(str(value), secrets) or ""
    return redacted


def redact_url(url: str, secrets: Iterable[str]) -> str:
    """
    Redacts secrets from a URL regardless of how they were percent-encoded
    (mixed, lowercase or ``+`` for spaces). The URL is returned decoded only
    when a secret is found that way.
    """
    secrets = list(secrets)
    redacted = redact_text(url, secrets) or ""
    for decode in (unquote, unquote_plus):
        decoded = decode(redacted)
        cleaned = redact_text(decoded, secrets)
        if cleaned != decoded:
            return cleaned or ""
    return redacted


def _redact_json_value(value: Any, secrets: List[str]) -> Any:
    if isinstance(value, dict):
        return {redact_text(k, secrets): _redact_json_value(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json_value(v, secrets) for v in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    if value is not None and json.dumps(value) in secrets:
        return REDACTED
    return value


def redact_body(text: Optional[str], secrets: Iterable[str]) -> Optional[str]:
    """
    Like ``redact_text``, but keeps JSON bodies valid JSON: values are
    redacted structurally, so a secret matching a literal (``true``, ``1234``)
    becomes the string marker instead of breaking the document.
    """
    secrets = list(secrets)
    if not text or not secrets:
        return text
    try:
        parsed = json.loads(text)
    except ValueError:
        return redact_text(text, secrets)
    if not isinstance(parsed, (dict, list)):
        return redact_text(text, secrets)
    redacted = _redact_json_value(parsed, secrets)
    if redacted == parsed:
        return text
    return json.dumps(redacted)
