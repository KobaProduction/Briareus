"""Verified provider facts, never Platform membership or Cedar grants."""

from dataclasses import dataclass, field
from datetime import datetime

from .native_login import SecretText


class OidcIdentityRejected(Exception):
    """Provider identity proof was rejected."""


class OidcIdentityKeysUnavailable(Exception):
    """Provider signing authority could not be verified."""


class OidcProviderUnavailable(Exception):
    """Provider protocol or discovery unavailable."""


class OidcSessionStoreUnavailable(Exception):
    """Private transaction/session storage did not confirm the operation."""


class RefreshNotDispatched(Exception):
    """A rotating refresh credential has not reached the provider."""


@dataclass(frozen=True, slots=True)
class VerifiedOidcIdentity:
    issuer: str
    subject: str
    client_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PrivateOidcResourceCredential:
    issuer: str
    subject: str
    client_id: str
    audience: str
    expires_at: datetime
    bearer: SecretText = field(repr=False)


@dataclass(frozen=True, slots=True)
class VerifiedRefreshCredential:
    token: SecretText = field(repr=False)
    not_before: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerifiedOidcLogin:
    identity: VerifiedOidcIdentity
    resource: PrivateOidcResourceCredential | None
    refresh: VerifiedRefreshCredential | None = None


@dataclass(frozen=True, slots=True)
class OidcAuthorizationAttempt:
    authorization_url: str
    state: str
    nonce: str
    code_verifier: SecretText = field(repr=False)
    redirect_uri: str
    expires_at: datetime
    resource_audience: str | None = None


@dataclass(frozen=True, slots=True)
class PrivateOidcPending:
    nonce: str
    verifier: SecretText = field(repr=False)
    issuer: str
    client_id: str
    resource_audience: str | None
    expires_at: datetime
