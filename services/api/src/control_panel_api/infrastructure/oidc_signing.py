"""Pinned JWKS HTTP/SDK adapter and strict decoding of verified JWT claim fields."""

import json

import httpx
import jwt
from pydantic import BaseModel, StrictInt, StrictStr, TypeAdapter, ValidationError

from control_panel_api.domain.oidc_identity import OidcIdentityKeysUnavailable, OidcIdentityRejected
from control_panel_api.domain.oidc_signing import (
    IdTokenIntent,
    OidcIdTokenClaims,
    ProviderSigningHeader,
    checked_signing_header,
    require_provider_token,
    require_signing_key,
)
from control_panel_api.infrastructure._oidc_bindings import _ClientBinding
from runtime_peer.oidc_wire import EdwardsSigningKey, IssuerSigningHeader, IssuerSigningKey


def provider_signing_header(raw: str) -> ProviderSigningHeader:
    try:
        header = IssuerSigningHeader.model_validate(jwt.get_unverified_header(raw))
        return checked_signing_header(
            kid=header.kid,
            algorithm=header.alg,
            critical=header.critical,
            external_key=False,
        )
    except (jwt.PyJWTError, ValidationError) as exc:
        raise OidcIdentityRejected("malformed Rauthy ID token") from exc


def _selected_jwk(material: object, kid: str) -> IssuerSigningKey:
    if not isinstance(material, dict):
        raise OidcIdentityKeysUnavailable("invalid JWKS object")
    keys = material.get("keys")
    if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
        raise OidcIdentityKeysUnavailable("signing keys unavailable")
    matching = [key for key in keys if isinstance(key, dict) and key.get("kid") == kid]
    if len(matching) != 1:
        raise OidcIdentityRejected("unknown or duplicate ID token key")
    return TypeAdapter[IssuerSigningKey](IssuerSigningKey).validate_python(matching[0])


async def verified_provider_key(
    raw: str,
    *,
    issuer: str,
    jwks_uri: str,
    client: httpx.AsyncClient,
) -> jwt.PyJWK:
    require_provider_token(raw, issuer=issuer, jwks_uri=jwks_uri)
    signing = provider_signing_header(raw)
    try:
        response = await client.get(
            jwks_uri, headers={"Accept": "application/json"}, follow_redirects=False
        )
        response.raise_for_status()
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if len(response.content) > 65536 or mime not in {
            "application/json",
            "application/jwk-set+json",
        }:
            raise OidcIdentityKeysUnavailable("untrusted JWKS response")
        key = _selected_jwk(response.json(), signing.kid)
        require_signing_key(
            expected_algorithm=signing.algorithm,
            algorithm=key.alg,
            usage=key.use,
            key_type=key.kty,
            curve=key.crv if isinstance(key, EdwardsSigningKey) else None,
            external_or_private=False,
        )
        return jwt.PyJWK.from_dict(key.model_dump(exclude_unset=True), algorithm=signing.algorithm)
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise OidcIdentityKeysUnavailable("issuer signing keys unavailable") from exc


class SignedIdClaims(BaseModel):
    sub: StrictStr
    aud: StrictStr
    azp: StrictStr | None = None
    iat: StrictInt
    exp: StrictInt
    nonce: StrictStr

    def claims(self) -> OidcIdTokenClaims:
        return OidcIdTokenClaims(self.sub, self.aud, self.azp, self.iat, self.exp, self.nonce)


class JwtOidcIdSignature(_ClientBinding[httpx.AsyncClient]):
    async def decode(self, raw: str, intent: IdTokenIntent) -> OidcIdTokenClaims:
        key = await verified_provider_key(
            raw, issuer=intent.issuer, jwks_uri=intent.jwks_uri, client=self._client
        )
        try:
            claims = jwt.decode(
                raw,
                key.key,
                algorithms=[key.algorithm_name],
                issuer=intent.issuer,
                audience=intent.client_id,
                leeway=0,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"]},
            )
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError) as exc:
            raise OidcIdentityRejected("Rauthy ID token invalid or expired") from exc
        try:
            return SignedIdClaims.model_validate(claims).claims()
        except ValidationError:
            raise OidcIdentityRejected("ID token actor, audience or nonce mismatched") from None
