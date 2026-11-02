"""Exact provider realm/PKCE intent and current signed-user identity constraints."""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import urlsplit

from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    OidcProviderUnavailable,
    VerifiedOidcIdentity,
)


def is_https_url(value: str) -> bool:
    try:
        url = urlsplit(value)
    except ValueError:
        return False
    return (
        url.scheme == "https"
        and bool(url.hostname)
        and url.username is None
        and url.password is None
        and not url.fragment
        and not url.query
    )


def rauthy_endpoint(issuer: str, url: str, name: str) -> bool:
    if not is_https_url(issuer) or not is_https_url(url):
        return False
    expected, endpoint = urlsplit(issuer), urlsplit(url)
    return (
        endpoint.netloc == expected.netloc
        and endpoint.path == expected.path.rstrip("/") + "/oidc/" + name
    )


@dataclass(frozen=True, slots=True)
class OidcProviderEndpoints:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    response_types: tuple[str, ...]
    challenge_methods: tuple[str, ...]

    def require_pinned(self, issuer: str) -> None:
        endpoints_match = (
            self.issuer.rstrip("/") == issuer
            and rauthy_endpoint(issuer, self.authorization_endpoint, "authorize")
            and rauthy_endpoint(issuer, self.token_endpoint, "token")
            and rauthy_endpoint(issuer, self.jwks_uri, "certs")
            and self.userinfo_endpoint is not None
            and rauthy_endpoint(issuer, self.userinfo_endpoint, "userinfo")
        )
        if (
            not endpoints_match
            or "code" not in self.response_types
            or "S256" not in self.challenge_methods
        ):
            raise OidcProviderUnavailable(
                "OIDC issuer metadata violates pinned Rauthy PKCE endpoints"
            )


def require_code_exchange(
    *,
    code: str,
    redirect_uri: str,
    verifier: SecretText,
    resource_audience: str | None,
    expected_resource: str | None,
) -> None:
    if (
        resource_audience != expected_resource
        or not _valid_code(code)
        or not is_https_url(redirect_uri)
        or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", verifier.get_secret_value()) is None
    ):
        raise ValueError("invalid code or trusted PKCE transaction")


def _valid_code(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 4096
        and not any(character.isspace() for character in value)
    )


def require_userinfo_identity(
    identity: VerifiedOidcIdentity,
    *,
    issuer: str,
    client_id: str,
    now: datetime,
) -> None:
    if (
        identity.issuer.rstrip("/") != issuer
        or identity.client_id != client_id
        or re.fullmatch(r"[A-Za-z0-9]{24}", identity.subject, re.ASCII) is None
        or identity.expires_at <= now
    ):
        raise OidcIdentityRejected("Rauthy Userinfo signed subject unavailable")


def require_userinfo_bearer(raw: str) -> None:
    if (
        not 40 <= len(raw) <= 8192
        or not raw.isascii()
        or any(character.isspace() for character in raw)
    ):
        raise OidcIdentityRejected("Rauthy bearer not suitable for Userinfo")


def bounded_identity(identity: VerifiedOidcIdentity, expires_at: datetime) -> VerifiedOidcIdentity:
    return replace(identity, expires_at=min(identity.expires_at, expires_at))


def require_original_intent(
    *,
    expected_issuer: str,
    issuer: str,
    expected_resource: str | None,
    resource_audience: str | None,
) -> None:
    if expected_issuer.rstrip("/") != issuer or expected_resource != resource_audience:
        raise OidcIdentityRejected("original OAuth intent no longer matches this realm")
