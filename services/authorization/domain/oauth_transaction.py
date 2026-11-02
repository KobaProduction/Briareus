"""Pending legacy OAuth consent state, independent of SDK and SQLAlchemy records."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AuthorizationIntent:
    state: str | None
    scopes: tuple[str, ...] | None
    code_challenge: str
    redirect_uri: str
    redirect_uri_provided_explicitly: bool
    resource: str | None


@dataclass(frozen=True, slots=True)
class AuthorizationTransaction:
    # The transaction selector is a cryptographic OAuth nonce, not a user UUID.
    id: str
    client_id: str
    parameters: AuthorizationIntent
    expires_at: datetime
