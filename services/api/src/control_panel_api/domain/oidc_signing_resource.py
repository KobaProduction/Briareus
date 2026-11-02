"""Resource bearer purpose and original identity/deadline constraints."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    PrivateOidcResourceCredential,
    VerifiedOidcIdentity,
)


@dataclass(frozen=True, slots=True)
class ResourceTokenIntent:
    identity: VerifiedOidcIdentity
    audience: str
    token_deadline: datetime
    jwks_uri: str
    token_client_id: str | None

    @property
    def expected_client(self) -> str:
        return self.token_client_id or self.identity.client_id

    @property
    def maximum_seconds(self) -> int:
        return 300 if self.token_client_id else 86400


@dataclass(frozen=True, slots=True)
class OidcResourceClaims:
    subject: str
    authorized_party: str
    purpose: str
    audience: tuple[str, ...]
    issued_at: int
    not_before: int
    expires_at: int
    jti: str
    confirmation_bound: bool
    delegated_actor: bool

    def credential(
        self,
        intent: ResourceTokenIntent,
        token: SecretText,
        now: Callable[[], datetime],
    ) -> PrivateOidcResourceCredential:
        self._require_purpose(intent)
        self._require_lifetime(intent.maximum_seconds)
        self._require_jti()
        expires = min(
            intent.identity.expires_at,
            intent.token_deadline,
            datetime.fromtimestamp(self.expires_at, UTC),
        )
        if expires <= now():
            raise OidcIdentityRejected("resource token lifetime already expired")
        identity = intent.identity
        return PrivateOidcResourceCredential(
            identity.issuer, identity.subject, identity.client_id, intent.audience, expires, token
        )

    def _require_purpose(self, intent: ResourceTokenIntent) -> None:
        expected = {intent.expected_client, intent.audience}
        if (
            self.subject != intent.identity.subject
            or self.authorized_party != intent.expected_client
            or self.purpose != "Bearer"
            or self.confirmation_bound
            or self.delegated_actor
            or len(self.audience) != 2
            or set(self.audience) != expected
        ):
            raise OidcIdentityRejected("resource token purpose or original identity mismatched")

    def _require_lifetime(self, maximum: int) -> None:
        if (
            not 0 < self.expires_at - self.issued_at <= maximum
            or self.not_before >= self.expires_at
        ):
            raise OidcIdentityRejected("resource token purpose or original identity mismatched")

    def _require_jti(self) -> None:
        if (
            not 1 <= len(self.jti) <= 128
            or not self.jti.isascii()
            or any(ord(character) <= 32 or ord(character) >= 127 for character in self.jti)
        ):
            raise OidcIdentityRejected("resource token purpose or original identity mismatched")
