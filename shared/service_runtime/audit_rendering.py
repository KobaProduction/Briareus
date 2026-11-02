from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence

MAX_PAYLOAD_CHARS = 65_536
REDACTED = "<redacted>"

_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set_cookie",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "client_secret",
    "credential",
    "private_key",
    "private_key_pem",
    "api_key",
    "download_url",
    "jwt",
    "id_token",
}

_TEXT_SECRET_PATTERNS = (
    re.compile(r"(?i)(\bauthorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)(\b(?:private-token|job-token)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(\bBearer\s+)[^\s,;]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(
        r"(?i)(\b(?:access_token|refresh_token|token|password|secret|client_secret|api_key)"
        r"\s*[:=]\s*)[^\s&;,]+"
    ),
    re.compile(
        r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
        re.IGNORECASE | re.DOTALL,
    ),
)

_SENSITIVE_SUFFIXES = (
    "_token",
    "_password",
    "_secret",
    "_credential",
    "_private_key",
    "_api_key",
    "_jwt",
)


def _key_is_sensitive(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _dataclass_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            return dataclasses.asdict(value)
        except Exception:
            return value
    return value


def _structured(value: object) -> object:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except Exception:
            return _dataclass_value(value)
    return _dataclass_value(value)


def redact_json(value: object) -> str:
    """Serialize native audit input; consumers must decode their concrete event schema."""
    value = _structured(value)
    if isinstance(value, Mapping):
        # Preserve last-value semantics when distinct native keys stringify equally.
        fields = {
            str(key): json.dumps(REDACTED, ensure_ascii=False)
            if _key_is_sensitive(key)
            else redact_json(item)
            for key, item in value.items()
        }
        return (
            "{"
            + ", ".join(
                f"{json.dumps(key, ensure_ascii=False)}: {encoded}"
                for key, encoded in fields.items()
            )
            + "}"
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ", ".join(redact_json(item) for item in value) + "]"
    sanitized = redact_text(value) if isinstance(value, str) else value
    try:
        return json.dumps(sanitized, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps(repr(sanitized), ensure_ascii=False)


def render_payload(value: object) -> str:
    return redact_json(value)[:MAX_PAYLOAD_CHARS]


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _TEXT_SECRET_PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
        else:
            redacted = pattern.sub(REDACTED, redacted)
    return redacted


def render_error(value: object) -> str:
    return redact_text(str(value))[:MAX_PAYLOAD_CHARS]
