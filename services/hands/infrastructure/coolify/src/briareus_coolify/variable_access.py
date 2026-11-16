from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass

from briareus_environment_models import ProcessSettings
from briareus_json_values import JsonObject
from pydantic import Field

# Never return raw shared values, including through application-level references.
_SHARED_REFERENCE = re.compile(r"\{\{\s*(?:team|project|environment|server)\.[^{}]+\}\}", re.I)
_REDACTED_VALUE = re.compile(r"^[*•●]{6,}$")


class CoolifyReadSettings(ProcessSettings):
    confirmation_ttl_seconds: int = Field(
        120, ge=30, le=600, validation_alias="COOLIFY_READ_CONFIRM_TTL_SECONDS"
    )
    max_pending_confirmations: int = Field(
        256, ge=1, le=1024, validation_alias="COOLIFY_READ_CONFIRM_MAX_PENDING"
    )

_SAFE_METADATA = (
    "uuid",
    "key",
    "is_preview",
    "is_runtime",
    "is_buildtime",
    "is_shared",
    "is_shown_once",
    "is_locked",
    "is_literal",
    "is_multiline",
    "version",
    "created_at",
    "updated_at",
)


def _locked(variable: JsonObject) -> bool:
    return variable.get("is_shown_once") is True or variable.get("is_locked") is True


def shared_reference(variable: JsonObject) -> bool:
    if variable.get("is_shared") is True:
        return True
    return any(
        isinstance(value, str) and bool(_SHARED_REFERENCE.search(value))
        for field in ("value", "real_value")
        if (value := variable.get(field)) is not None
    )


def available_value(variable: JsonObject) -> str | None:
    """Only explicit upstream strings; never guess a redacted or locked value."""
    if _locked(variable):
        return None
    for name in ("real_value", "value"):
        value = variable.get(name)
        if isinstance(value, str) and not _REDACTED_VALUE.fullmatch(value):
            return value
    return None


def masked_preview(value: str) -> str:
    """Hide the entire secret for short values; never reveal more than 2+2 chars."""
    length = len(value)
    if length < 8:
        return "*" * length
    return value[:2] + "*" * min(32, length - 4) + value[-2:]


def variable_summary(variable: JsonObject, *, masked: bool = False) -> JsonObject:
    """Project metadata and optional irreversible mask; no raw value escapes."""
    result: JsonObject = {k: variable[k] for k in _SAFE_METADATA if k in variable}
    value = available_value(variable)
    result["configured"] = value != "" if value is not None else None
    result["value_length"] = len(value) if value is not None else None
    result["value_status"] = (
        "locked" if _locked(variable)
        else "unavailable" if value is None
        else "empty" if not value
        else "configured"
    )
    if masked:
        result["masked_value"] = masked_preview(value) if value is not None else None
    return result


def safe_shared_variable(variable: JsonObject, *, masked: bool) -> JsonObject:
    """Force shared status regardless of provider flags; raw value is never returned."""
    result = variable_summary(variable, masked=masked)
    result["is_shared"] = True
    return result


def app_variable_value(variable: JsonObject) -> str:
    if _locked(variable):
        raise ValueError("Locked application variables cannot be read")
    if shared_reference(variable):
        raise ValueError("Shared or shared-referencing application variables cannot be read")
    value = available_value(variable)
    if value is None:
        raise ValueError("Coolify did not expose this value; read:sensitive may be required")
    if len(value) > 65_536:
        raise ValueError("Application variable exceeds the maximum permitted read size")
    return value


@dataclass(frozen=True)
class PendingRead:
    account: str
    application: str
    variable: str
    expires_at: float


class VariableReadConfirmation:
    """One-time process-local approval challenge. No secret value is stored."""

    def __init__(self, settings: CoolifyReadSettings | None = None) -> None:
        self.settings = settings or CoolifyReadSettings()
        self._lock = threading.Lock()
        self._pending: dict[str, PendingRead] = {}

    def issue(self, account: str, application: str, variable: str) -> str:
        now = time.monotonic()
        with self._lock:
            self._pending = {
                key: value for key, value in self._pending.items() if value.expires_at > now
            }
            if len(self._pending) >= self.settings.max_pending_confirmations:
                raise ValueError("Too many pending variable read confirmations")
            challenge = secrets.token_urlsafe(32)
            self._pending[challenge] = PendingRead(
                account, application, variable, now + self.settings.confirmation_ttl_seconds
            )
            return challenge

    def consume(
        self,
        challenge: str,
        *,
        account: str,
        application: str,
        variable: str,
        permission_confirmed: bool,
        purpose: str,
    ) -> None:
        if permission_confirmed is not True:
            raise ValueError("Explicit permission confirmation is required")
        if not 12 <= len(purpose.strip()) <= 500:
            raise ValueError("Provide a specific 12-500 character purpose before reading")
        with self._lock:
            grant = self._pending.pop(challenge, None)
        if grant is None or grant.expires_at <= time.monotonic():
            raise ValueError("Read confirmation is invalid, expired or already used")
        if (grant.account, grant.application, grant.variable) != (
            account, application, variable
        ):
            raise ValueError("Read confirmation is not valid for this account, application and key")
