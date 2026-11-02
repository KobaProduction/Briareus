"""Bounded, strict decoding of the pinned private Rauthy UserResponse."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from projects.domain.user_links import PlatformRole, VerifiedRauthyUserStatus


class RauthyUserStatusUnavailable(Exception):
    """Private upstream status or Users:read authority is not trusted."""


@dataclass(frozen=True, slots=True)
class PrivateUserResponse:
    status: int
    content_type: str
    body: bytes


class ProviderUserStatusWire(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    id: str
    enabled: bool
    roles: list[str] = Field(max_length=256)
    user_expires: int | None = Field(default=None, ge=1, le=2**63 - 1)
    email: str | None = None
    given_name: str | None = None
    family_name: str | None = None

    @field_validator("roles")
    @classmethod
    def role_names(cls, value: list[str]) -> list[str]:
        if any(not 1 <= len(role) <= 64 for role in value) or len(set(value)) != len(value):
            raise ValueError("Invalid provider roles")
        return value

    @field_validator("email", "given_name", "family_name", mode="before")
    @classmethod
    def display_label(cls, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return (
            value if 0 < len(value) <= 255 and not any(ord(char) < 32 for char in value) else None
        )


def validate_unique_keys(pairs: list[tuple[str, object]]) -> None:
    # This first bounded parse validates every object's keys and intentionally
    # discards its values. Pydantic performs the independent typed decode.
    names: set[str] = set()
    for key, _value in pairs:
        if key in names:
            raise ValueError("duplicate Rauthy Users API JSON field")
        names.add(key)


def valid_response_body(value: object) -> bool:
    return isinstance(value, bytes) and 1 <= len(value) <= 65536


def require_status_response(response: PrivateUserResponse) -> None:
    if response.status != 200 or response.content_type.split(";", 1)[0] != "application/json":
        raise RauthyUserStatusUnavailable("Rauthy Users:read not verified")
    if not valid_response_body(response.body):
        raise RauthyUserStatusUnavailable("Rauthy Users:read not verified")


def decode_user_status(
    response: PrivateUserResponse,
    issuer: str,
    subject: str,
    now: datetime,
) -> VerifiedRauthyUserStatus:
    if not isinstance(response, PrivateUserResponse):
        raise RauthyUserStatusUnavailable("untrusted Rauthy Users response")
    expiry = now + timedelta(seconds=10)
    if response.status == 404:
        return VerifiedRauthyUserStatus(issuer, subject, False, expiry)
    require_status_response(response)
    try:
        json.loads(response.body, object_pairs_hook=validate_unique_keys)
        wire = ProviderUserStatusWire.model_validate_json(response.body)
    except (UnicodeDecodeError, ValueError, TypeError):
        raise RauthyUserStatusUnavailable("Rauthy Users body invalid") from None
    if wire.id != subject:
        raise RauthyUserStatusUnavailable("Rauthy User identity/status mismatch")
    active = wire.enabled
    if wire.user_expires is not None:
        try:
            account_expiry = datetime.fromtimestamp(wire.user_expires, tz=UTC)
        except (OverflowError, OSError, ValueError):
            raise RauthyUserStatusUnavailable("Rauthy account expiry invalid") from None
        active = active and account_expiry > now
        if active:
            expiry = min(expiry, account_expiry)
    name = (
        ProviderUserStatusWire.display_label(
            " ".join(filter(None, (wire.given_name, wire.family_name)))
        )
        or wire.email
    )
    role: PlatformRole = "operator" if "rauthy_admin" in wire.roles else "user"
    return VerifiedRauthyUserStatus(issuer, subject, active, expiry, name, wire.email, role)
