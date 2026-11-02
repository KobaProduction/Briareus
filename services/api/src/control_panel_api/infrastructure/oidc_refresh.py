"""Pinned HTTP rotation, JWT verification and strict refresh-purpose claim decoding."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import jwt
from pydantic import BaseModel, SecretStr, StrictInt, StrictStr

from control_panel_api.application.oidc_provider_contracts import UnverifiedOidcTokenResponse
from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.oidc_identity import (
    OidcIdentityRejected,
    OidcProviderUnavailable,
    PrivateOidcResourceCredential,
    RefreshNotDispatched,
    VerifiedOidcIdentity,
)
from control_panel_api.domain.oidc_refresh import (
    RefreshClaims,
    RefreshedIdClaims,
    RefreshEndpoints,
    RefreshIntent,
)
from control_panel_api.infrastructure._oidc_bindings import _ProviderBinding
from control_panel_api.infrastructure.json_fields import validate_unique_fields
from control_panel_api.infrastructure.oidc_signing import verified_provider_key

if TYPE_CHECKING:
    from control_panel_api._oidc import RauthyOidcAdapter


class SignedRefreshClaims(BaseModel):
    typ: StrictStr
    uid: StrictStr
    aud: StrictStr
    azp: StrictStr
    resource: StrictStr | None = None
    iat: StrictInt
    nbf: StrictInt
    exp: StrictInt

    def claims(self) -> RefreshClaims:
        return RefreshClaims(
            self.typ, self.uid, self.aud, self.azp, self.resource, self.iat, self.nbf, self.exp
        )


class SignedRefreshedIdClaims(BaseModel):
    sub: StrictStr
    aud: StrictStr
    azp: StrictStr
    typ: StrictStr
    nonce: StrictStr | None = None
    iat: StrictInt
    exp: StrictInt

    def claims(self) -> RefreshedIdClaims:
        return RefreshedIdClaims(
            self.sub, self.aud, self.azp, self.typ, self.nonce, self.iat, self.exp
        )


def rotated_tokens(response: httpx.Response, began: datetime) -> UnverifiedOidcTokenResponse:
    if response.status_code in {400, 401, 403}:
        raise OidcIdentityRejected("Provider rejected session renewal")
    if (
        response.status_code != 200
        or len(response.content) > 65536
        or response.headers.get("content-type", "").split(";")[0] != "application/json"
    ):
        raise OidcProviderUnavailable("Provider renewal unavailable")
    try:
        validate_unique_fields(response.content)
        tokens = UnverifiedOidcTokenResponse.model_validate_json(response.content)
    except (ValueError, TypeError, OverflowError):
        raise OidcIdentityRejected("Refreshed provider identity invalid") from None
    tokens._request_started = began
    if tokens.token_type.lower() != "bearer":
        raise OidcIdentityRejected("Unexpected refresh token type")
    return tokens


class RauthyRefreshProvider(_ProviderBinding["RauthyOidcAdapter"]):
    _provider: "RauthyOidcAdapter"

    async def endpoints(self) -> RefreshEndpoints:
        metadata = await self._provider.discovery()
        return RefreshEndpoints(metadata.issuer, metadata.token_endpoint, metadata.jwks_uri)

    async def rotation_endpoints(self) -> RefreshEndpoints:
        try:
            return await self.endpoints()
        except (OidcProviderUnavailable, httpx.HTTPError):
            # Discovery precedes the rotating POST; the old credential was never sent.
            raise RefreshNotDispatched from None

    async def rotate(
        self, token: SecretText, endpoints: RefreshEndpoints
    ) -> UnverifiedOidcTokenResponse:
        began = datetime.now(UTC)
        try:
            response = await self._provider._client.post(
                endpoints.token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._provider.client_id,
                    "refresh_token": token.get_secret_value(),
                },
                headers={"Accept": "application/json"},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            # Only this token POST is known not to have reached the rotating authority.
            raise RefreshNotDispatched from None
        except httpx.HTTPError:
            raise OidcProviderUnavailable("Provider refresh transport unavailable") from None
        return rotated_tokens(response, began)

    async def refresh_claims(
        self, token: SecretText, intent: RefreshIntent, endpoints: RefreshEndpoints
    ) -> RefreshClaims:
        raw = token.get_secret_value()
        key = await verified_provider_key(
            raw, issuer=intent.issuer, jwks_uri=endpoints.jwks_uri, client=self._provider._client
        )
        try:
            claims = jwt.decode(
                raw,
                key.key,
                algorithms=[key.algorithm_name],
                issuer=intent.issuer,
                audience=intent.client_id,
                options={
                    "verify_nbf": False,
                    "require": ["iss", "aud", "exp", "iat", "nbf", "uid", "azp", "typ"],
                },
            )
            return SignedRefreshClaims.model_validate(claims).claims()
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
            raise OidcIdentityRejected("Refresh credential rejected") from None

    async def identity_claims(
        self, token: SecretText, intent: RefreshIntent, endpoints: RefreshEndpoints
    ) -> RefreshedIdClaims:
        raw = token.get_secret_value()
        key = await verified_provider_key(
            raw, issuer=endpoints.issuer, jwks_uri=endpoints.jwks_uri, client=self._provider._client
        )
        try:
            claims = jwt.decode(
                raw,
                key.key,
                algorithms=[key.algorithm_name],
                issuer=endpoints.issuer,
                audience=intent.client_id,
                options={"require": ["iss", "aud", "sub", "iat", "exp", "typ", "azp"]},
            )
            return SignedRefreshedIdClaims.model_validate(claims).claims()
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
            raise OidcIdentityRejected("Refreshed provider identity invalid") from None

    async def current_userinfo(
        self, tokens: UnverifiedOidcTokenResponse, identity: VerifiedOidcIdentity
    ) -> None:
        await self._provider.verify_current_userinfo(tokens=tokens, identity=identity)

    async def resource(
        self,
        tokens: UnverifiedOidcTokenResponse,
        identity: VerifiedOidcIdentity,
        audience: str,
        endpoints: RefreshEndpoints,
    ) -> PrivateOidcResourceCredential:
        from control_panel_api._oidc_resource import verify_resource_credential

        return await verify_resource_credential(
            token=SecretStr(tokens.access_token.get_secret_value()),
            identity=identity,
            resource_audience=audience,
            token_deadline=tokens.deadline,
            jwks_uri=endpoints.jwks_uri,
            client=self._provider._client,
        )
