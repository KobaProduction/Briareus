"""Typed provider protocol messages; unverified tokens never imply local grants."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr

from control_panel_api.domain.oidc_provider import OidcProviderEndpoints

_utc_now = partial(datetime.now, UTC)


class OidcDiscovery(BaseModel):
    model_config = ConfigDict(extra="ignore")
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None = None
    code_challenge_methods_supported: list[str] = Field(default_factory=list)
    response_types_supported: list[str] = Field(default_factory=list)
    grant_types_supported: list[str] = Field(default_factory=list)

    def endpoints(self) -> OidcProviderEndpoints:
        return OidcProviderEndpoints(
            self.issuer,
            self.authorization_endpoint,
            self.token_endpoint,
            self.jwks_uri,
            self.userinfo_endpoint,
            tuple(self.response_types_supported),
            tuple(self.code_challenge_methods_supported),
        )


@dataclass(frozen=True, slots=True)
class PublicOidcConfiguration:
    issuer: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None


class UnverifiedOidcTokenResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    access_token: SecretStr = Field(min_length=40)
    id_token: SecretStr = Field(min_length=40)
    token_type: str
    expires_in: int = Field(strict=True, gt=0, le=86400)
    refresh_token: SecretStr | None = None
    _request_started: datetime = PrivateAttr(default_factory=_utc_now)

    @property
    def deadline(self) -> datetime:
        return self._request_started + timedelta(seconds=self.expires_in)
