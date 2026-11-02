"""Pinned provider signing purpose, signer metadata and ID-token identity rules."""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from control_panel_api.domain.oidc_identity import OidcIdentityRejected, VerifiedOidcIdentity

ALGORITHMS = frozenset({"EdDSA", "RS256", "RS384", "RS512"})


def trusted_jwks_location(issuer: str, uri: str) -> bool:
    parent, key_uri = urlsplit(issuer), urlsplit(uri)
    return bool(
        parent.scheme == "https"
        and parent.hostname
        and parent.username is None
        and parent.password is None
        and not parent.query
        and not parent.fragment
        and issuer.endswith("/")
        and key_uri.scheme == "https"
        and key_uri.netloc == parent.netloc
        and key_uri.username is None
        and key_uri.password is None
        and not key_uri.query
        and not key_uri.fragment
        and key_uri.path.startswith(parent.path)
        and key_uri.path != parent.path
    )


@dataclass(frozen=True, slots=True)
class ProviderSigningHeader:
    kid: str
    algorithm: str


def checked_signing_header(
    *,
    kid: str,
    algorithm: str,
    critical: bool,
    external_key: bool,
) -> ProviderSigningHeader:
    if not 1 <= len(kid) <= 128 or algorithm not in ALGORITHMS or critical or external_key:
        raise OidcIdentityRejected("ID token signing metadata rejected")
    return ProviderSigningHeader(kid, algorithm)


def require_provider_token(raw: str, *, issuer: str, jwks_uri: str) -> None:
    if not 80 <= len(raw) <= 8192 or not trusted_jwks_location(issuer, jwks_uri):
        raise OidcIdentityRejected("provider token or trusted issuer proof missing")


def require_signing_key(
    *,
    expected_algorithm: str,
    algorithm: str,
    usage: str | None,
    key_type: str,
    curve: str | None,
    external_or_private: bool,
) -> None:
    if algorithm != expected_algorithm or usage != "sig" or external_or_private:
        raise OidcIdentityRejected("ID token signing key not trusted")
    if expected_algorithm == "EdDSA":
        if key_type != "OKP" or curve != "Ed25519":
            raise OidcIdentityRejected("ID token signing key not trusted")
    elif key_type != "RSA":
        raise OidcIdentityRejected("ID token signing key not trusted")


@dataclass(frozen=True, slots=True)
class IdTokenIntent:
    nonce: str
    issuer: str
    client_id: str
    jwks_uri: str

    def require_token(self, raw: str) -> None:
        if (
            not 80 <= len(raw) <= 8192
            or not _valid_nonce(self.nonce)
            or not self.client_id
            or not trusted_jwks_location(self.issuer, self.jwks_uri)
        ):
            raise OidcIdentityRejected("OIDC ID token or trusted issuer proof missing")


def _valid_nonce(value: object) -> bool:
    return isinstance(value, str) and 32 <= len(value) <= 128


@dataclass(frozen=True, slots=True)
class OidcIdTokenClaims:
    subject: str
    audience: str
    authorized_party: str | None
    issued_at: int
    expires_at: int
    nonce: str

    def identity(self, intent: IdTokenIntent) -> VerifiedOidcIdentity:
        if (
            not 1 <= len(self.subject) <= 256
            or self.audience != intent.client_id
            or self.authorized_party not in (None, intent.client_id)
            or not 0 < self.expires_at - self.issued_at <= 3600
            or not hmac.compare_digest(self.nonce, intent.nonce)
        ):
            raise OidcIdentityRejected("ID token actor, audience or nonce mismatched")
        return VerifiedOidcIdentity(
            intent.issuer,
            self.subject,
            intent.client_id,
            datetime.fromtimestamp(self.expires_at, tz=UTC),
        )
