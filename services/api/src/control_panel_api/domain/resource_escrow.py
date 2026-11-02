"""Derived credentials belong to one unchanged, revocable OIDC source."""

import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime

from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
)


class ResourceCredentialUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CachedResource:
    audience: str
    bearer: SecretText = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class EscrowSnapshot:
    version: str = field(repr=False)
    issuer: str
    subject: str
    client_id: str
    expires_at: datetime
    source_deadline: datetime
    source_bearer: SecretText = field(repr=False)
    resources: tuple[CachedResource, ...]

    def belongs_to(self, identity: VerifiedOidcIdentity) -> bool:
        return (self.issuer, self.subject, self.client_id) == (
            identity.issuer,
            identity.subject,
            identity.client_id,
        )

    def derives_from(
        self, identity: VerifiedOidcIdentity, source: PrivateOidcResourceCredential
    ) -> bool:
        return self.belongs_to(identity) and hmac.compare_digest(
            self.source_bearer.get_secret_value(), source.bearer.get_secret_value()
        )

    def cached(
        self, identity: VerifiedOidcIdentity, audience: str
    ) -> PrivateOidcResourceCredential | None:
        if not self.belongs_to(identity):
            return None
        for resource in self.resources:
            if resource.audience != audience:
                continue
            deadline = min(
                self.expires_at, self.source_deadline, resource.expires_at, identity.expires_at
            )
            if deadline <= datetime.now(UTC):
                return None
            return PrivateOidcResourceCredential(
                identity.issuer,
                identity.subject,
                identity.client_id,
                audience,
                deadline,
                resource.bearer,
            )
        return None


def valid_derived(
    resource: object,
    identity: VerifiedOidcIdentity,
    source: PrivateOidcResourceCredential,
    audience: str,
) -> bool:
    return (
        isinstance(resource, PrivateOidcResourceCredential)
        and (resource.issuer, resource.subject, resource.client_id, resource.audience)
        == (identity.issuer, identity.subject, identity.client_id, audience)
        and datetime.now(UTC) < resource.expires_at <= min(source.expires_at, identity.expires_at)
    )
