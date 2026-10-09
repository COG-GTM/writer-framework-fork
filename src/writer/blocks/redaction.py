"""
Helpers for keeping resolved secrets out of block results and request logs.
"""

import json
import os
import re
from typing import Any, Iterable, List, Mapping, Optional, Set
from urllib.parse import quote, quote_plus

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


def collect_secret_values(
    vault: Optional[Any] = None, field_templates: Iterable[Any] = ()
) -> List[str]:
    """
    Returns the plaintext values that must never be echoed: every vault
    secret, plus every environment variable referenced as ``@{$NAME}`` in
    the given raw field templates. Longest first, so overlapping secrets are
    replaced whole.
    """
    secrets: Set[str] = set()
    if vault:
        _collect_strings(vault, secrets)
    for template in field_templates:
        if not isinstance(template, str):
            continue
        for match in _TEMPLATE_REGEX.finditer(template):
            expr = match.group(1).strip()
            if expr.startswith("$"):
                env_value = os.getenv(expr[1:])
                if env_value:
                    secrets.add(env_value)
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
