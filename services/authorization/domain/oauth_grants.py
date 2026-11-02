"""Immutable legacy OAuth grant facts without SQLAlchemy or SDK records."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AuthorizationCodeSnapshot:
    code: str = field(repr=False)
    client_id: str
    user_id: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    scopes: tuple[str, ...]
    resource: str
    code_challenge: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshTokenSnapshot:
    client_id: str
    user_id: str
    scopes: tuple[str, ...]
    resource: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class RefreshRotation:
    user_id: str
    resource: str
    session_id: str
