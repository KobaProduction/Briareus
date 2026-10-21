"""Pinned Rauthy 0.37.1 token rotation; refresh credentials never reach JS.

Source: Rauthy v0.37.1 service/oidc/validation.rs and token_set.rs.
Refresh ID tokens have no nonce; they require their own signature/purpose,
exact original subject/client and independently verified userinfo instead.
"""
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import httpx
import jwt
from pydantic import SecretStr

from ._oidc_id_token import OidcIdentityRejected, VerifiedOidcIdentity, _verified_provider_key


class RefreshNotDispatched(Exception):
    """No refresh credential reached the provider; retry remains safe."""


@dataclass(frozen=True, slots=True)
class VerifiedRefreshCredential:
    token: SecretStr
    not_before: datetime
    expires_at: datetime


async def capture_refresh(provider, tokens, identity):
    if tokens.refresh_token is None:
        return None
    metadata = await provider.discovery()
    raw = tokens.refresh_token.get_secret_value()
    key = await _verified_provider_key(raw, issuer=identity.issuer, jwks_uri=metadata.jwks_uri,
                                       client=provider._client)
    try:
        claims = jwt.decode(raw, key.key, algorithms=[key.algorithm_name], issuer=identity.issuer,
                            audience=identity.client_id, options={"verify_nbf": False,
                            "require": ["iss", "aud", "exp", "iat", "nbf", "uid", "azp", "typ"]})
        if (claims["typ"] != "Refresh" or claims["uid"] != identity.subject
            or claims["aud"] != identity.client_id or claims["azp"] != identity.client_id
            or claims.get("resource") != provider.resource_audience
            or any(type(claims[k]) is not int for k in ("exp", "iat", "nbf"))
            or not claims["nbf"] < claims["exp"] or not claims["iat"] < claims["exp"]):
            raise ValueError("Refresh binding invalid")
        return VerifiedRefreshCredential(tokens.refresh_token,
            datetime.fromtimestamp(claims["nbf"], UTC), datetime.fromtimestamp(claims["exp"], UTC))
    except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
        raise OidcIdentityRejected("Refresh credential rejected") from None


async def refresh_login(provider, *, token: SecretStr, subject: str):
    from ._oidc import OidcProviderUnavailable, UnverifiedOidcTokenResponse, VerifiedOidcLogin, _unique_oidc_fields
    from ._oidc_resource import verify_resource_credential
    import json
    try:
        metadata = await provider.discovery()
    except Exception as exc:
        from ._oidc import OidcProviderUnavailable
        if isinstance(exc, (OidcProviderUnavailable, httpx.HTTPError)):
            raise RefreshNotDispatched() from None
        raise
    began = datetime.now(UTC)
    try:
        try:
            response = await provider._client.post(metadata.token_endpoint, data={
                "grant_type": "refresh_token", "client_id": provider.client_id,
                "refresh_token": token.get_secret_value(),
            }, headers={"Accept": "application/json"})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            # Only the token POST has not been dispatched. A connection
            # failure fetching keys/userinfo AFTER this POST cannot be retried
            # with the old rotating credential.
            raise RefreshNotDispatched() from None
        if response.status_code in {400, 401, 403}:
            raise OidcIdentityRejected("Provider rejected session renewal")
        if (response.status_code != 200 or len(response.content) > 65536
            or response.headers.get("content-type", "").split(";")[0] != "application/json"):
            raise OidcProviderUnavailable("Provider renewal unavailable")
        tokens = UnverifiedOidcTokenResponse.model_validate(json.loads(response.content, object_pairs_hook=_unique_oidc_fields))
        tokens._request_started = began
        if tokens.token_type.lower() != "bearer":
            raise OidcIdentityRejected("Unexpected refresh token type")
        raw = tokens.id_token.get_secret_value()
        key = await _verified_provider_key(raw, issuer=metadata.issuer, jwks_uri=metadata.jwks_uri,
                                           client=provider._client)
        claims = jwt.decode(raw, key.key, algorithms=[key.algorithm_name], issuer=metadata.issuer,
                            audience=provider.client_id, options={"require": ["iss", "aud", "sub", "iat", "exp", "typ", "azp"]})
        if (claims["sub"] != subject or claims["aud"] != provider.client_id
            or claims["azp"] != provider.client_id or claims["typ"] != "Id"
            or claims.get("nonce") is not None
            or type(claims["iat"]) is not int or type(claims["exp"]) is not int
            or not 0 < claims["exp"] - claims["iat"] <= 3600):
            raise OidcIdentityRejected("Refreshed identity changed")
        identity = VerifiedOidcIdentity(metadata.issuer, subject, provider.client_id,
                                        min(datetime.fromtimestamp(claims["exp"], UTC), tokens.deadline))
        await provider.verify_current_userinfo(tokens=tokens, identity=identity)
        resource = None
        if provider.resource_audience is not None:
            resource = await verify_resource_credential(token=tokens.access_token, identity=identity,
                resource_audience=provider.resource_audience, token_deadline=tokens.deadline,
                jwks_uri=metadata.jwks_uri, client=provider._client)
            identity = replace(identity, expires_at=min(identity.expires_at, resource.expires_at))
        renewal = await capture_refresh(provider, tokens, identity)
        return VerifiedOidcLogin(identity, resource, renewal)
    except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
        raise OidcIdentityRejected("Refreshed provider identity invalid") from None
    except httpx.HTTPError:
        raise OidcProviderUnavailable("Provider refresh transport unavailable") from None
