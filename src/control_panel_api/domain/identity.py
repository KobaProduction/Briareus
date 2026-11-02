from __future__ import annotations

from dataclasses import dataclass, field

PANEL_SESSION_KEY = "bri_identity_session"
PANEL_LOGIN_KEY = "bri_identity_login"


@dataclass(frozen=True)
class LoginTransaction:
    state: str
    verifier: str = field(repr=False)
    nonce: str = field(repr=False)
    expires_at: int


@dataclass(frozen=True)
class IdentityGrant:
    subject: str
    issuer: str
    display_name: str
    expires_at: int
    access_token: str = field(repr=False)
    id_token: str = field(repr=False)
    refresh_token: str = field(repr=False)


@dataclass(frozen=True)
class PanelIdentitySession:
    identifier: str
    csrf_token: str = field(repr=False)
    grant: IdentityGrant


@dataclass(frozen=True)
class AuthorizationStart:
    state: str
    url: str
