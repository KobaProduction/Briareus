from __future__ import annotations

import re

from briareus_json_values import JsonObject, JsonValue, json_loads, json_object_list
from briareus_telemetry.audit_payloads import REDACTED, redact_text

_ASSIGNMENT = re.compile(
    r'''(?im)(\b[\w-]*(?:token|password|secret|credential|api_key|private_key)\s*[:=]\s*)'''
    r'''(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s&;,]+)'''
)
_URL_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s@]+@")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)


def _log_text(value: JsonValue) -> str:
    if isinstance(value, str):
        if not value.lstrip().startswith("["):
            return value
        try:
            decoded = json_loads(value, context="Coolify deployment logs")
        except ValueError:
            return value
        value = decoded
    rows = json_object_list(value, context="Coolify deployment logs")
    lines: list[str] = []
    for row in rows:
        output = row.get("output")
        if not isinstance(output, str):
            raise ValueError("Coolify deployment log entry.output must be a string")
        timestamp, stream = row.get("timestamp"), row.get("type")
        prefix = " ".join(item for item in (timestamp, stream) if isinstance(item, str))
        lines.append(f"{prefix} {output}".strip())
    return "\n".join(lines)


def validate_log_window(offset: int | None, max_chars: int) -> None:
    if offset is not None and (isinstance(offset, bool) or offset < 0):
        raise ValueError("offset must be >= 0")
    if isinstance(max_chars, bool) or not 1 <= max_chars <= 100_000:
        raise ValueError("max_chars must be between 1 and 100000")


def deployment_log_page(
    deployment: JsonObject,
    *,
    credential: str,
    offset: int | None,
    max_chars: int,
) -> JsonObject:
    validate_log_window(offset, max_chars)
    raw = deployment.get("logs")
    if raw is None:
        return {
            "logs_available": False,
            "logs": None,
            "reason": "not_returned" if "logs" not in deployment else "null",
            "hint": "Coolify may omit logs without read:sensitive or root; "
            "this does not prove the journal is absent on the server.",
        }
    text = _log_text(raw)
    if credential:
        text = text.replace(credential, REDACTED)
    text = _PRIVATE_KEY.sub(REDACTED, text)
    text = redact_text(_ASSIGNMENT.sub(lambda m: m[1] + REDACTED, text))
    text = _URL_CREDENTIALS.sub(lambda m: m[1] + REDACTED + "@", text)
    start = max(0, len(text) - max_chars) if offset is None else min(offset, len(text))
    end = min(start + max_chars, len(text))
    return {
        "logs_available": True,
        "logs": text[start:end],
        "offset": start,
        "next_offset": end if end < len(text) else None,
        "total_chars": len(text),
        "truncated": start > 0 or end < len(text),
        "redaction": "best_effort",
    }
