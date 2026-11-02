"""Distinct Rauthy token purposes and original identity bindings during rotation."""

from dataclasses import dataclass
from datetime import UTC, datetime

from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    VerifiedOidcIdentity,
    VerifiedRefreshCredential,
)


def numeric_dates(values: tuple[object, ...]) -> bool:
    return all(type(value) is int for value in values)


@dataclass(frozen=True, slots=True)
class RefreshIntent:
    issuer: str
    client_id: str
    subject: str
    resource_audience: str | None


@dataclass(frozen=True, slots=True)
class RefreshEndpoints:
    issuer: str
    token_endpoint: str
    jwks_uri: str


@dataclass(frozen=True, slots=True)
class RefreshClaims:
    kind: str
    subject: str
    audience: str
    authorized_party: str
    resource: str | None
    issued_at: int
    not_before: int
    expires_at: int

    def credential(self, token: SecretText, intent: RefreshIntent) -> VerifiedRefreshCredential:
        if (
            not numeric_dates((self.issued_at, self.not_before, self.expires_at))
            or (self.kind, self.subject, self.audience, self.authorized_party, self.resource)
            != (
                "Refresh",
                intent.subject,
                intent.client_id,
                intent.client_id,
                intent.resource_audience,
            )
            or not self.not_before < self.expires_at
            or not self.issued_at < self.expires_at
        ):
            raise OidcIdentityRejected("Refresh credential rejected")
        try:
            return VerifiedRefreshCredential(
                token,
                datetime.fromtimestamp(self.not_before, UTC),
                datetime.fromtimestamp(self.expires_at, UTC),
            )
        except (ValueError, OverflowError, OSError):
            raise OidcIdentityRejected("Refresh credential rejected") from None


@dataclass(frozen=True, slots=True)
class RefreshedIdClaims:
    subject: str
    audience: str
    authorized_party: str
    kind: str
    nonce: str | None
    issued_at: int
    expires_at: int

    def identity(self, intent: RefreshIntent, deadline: datetime) -> VerifiedOidcIdentity:
        if (
            not numeric_dates((self.issued_at, self.expires_at))
            or (self.subject, self.audience, self.authorized_party, self.kind)
            != (intent.subject, intent.client_id, intent.client_id, "Id")
            or self.nonce is not None
            or not 0 < self.expires_at - self.issued_at <= 3600
        ):
            raise OidcIdentityRejected("Refreshed identity changed")
        try:
            expiry = min(datetime.fromtimestamp(self.expires_at, UTC), deadline)
        except (ValueError, TypeError, OverflowError, OSError):
            raise OidcIdentityRejected("Refreshed provider identity invalid") from None
        return VerifiedOidcIdentity(intent.issuer, intent.subject, intent.client_id, expiry)
