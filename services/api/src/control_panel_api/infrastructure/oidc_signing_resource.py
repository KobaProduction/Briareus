"""JWT verification and strict resource-purpose claim decoding at the SDK boundary."""

import httpx
import jwt
from pydantic import StrictInt, StrictStr, ValidationError

from control_panel_api.domain.oidc_identity import OidcIdentityRejected
from control_panel_api.domain.oidc_signing_resource import OidcResourceClaims, ResourceTokenIntent
from control_panel_api.infrastructure._oidc_bindings import _ClientBinding
from control_panel_api.infrastructure.oidc_signing import verified_provider_key
from runtime_peer.oidc_wire import BearerBindings


class SignedResourceClaims(BearerBindings):
    sub: StrictStr
    azp: StrictStr
    typ: StrictStr
    aud: list[StrictStr]
    iat: StrictInt
    nbf: StrictInt
    exp: StrictInt
    jti: StrictStr

    def claims(self) -> OidcResourceClaims:
        return OidcResourceClaims(
            self.sub,
            self.azp,
            self.typ,
            tuple(self.aud),
            self.iat,
            self.nbf,
            self.exp,
            self.jti,
            self.confirmation_bound,
            self.delegated_actor,
        )


class JwtOidcResourceSignature(_ClientBinding[httpx.AsyncClient]):
    async def decode(self, raw: str, intent: ResourceTokenIntent) -> OidcResourceClaims:
        key = await verified_provider_key(
            raw, issuer=intent.identity.issuer, jwks_uri=intent.jwks_uri, client=self._client
        )
        try:
            claims = jwt.decode(
                raw,
                key.key,
                algorithms=[key.algorithm_name],
                issuer=intent.identity.issuer,
                audience=intent.audience,
                leeway=0,
                options={
                    "require": ["iss", "aud", "sub", "iat", "nbf", "exp", "azp", "typ", "jti"]
                },
            )
        except (jwt.PyJWTError, TypeError, ValueError, OverflowError):
            raise OidcIdentityRejected("Rauthy resource bearer rejected") from None
        try:
            return SignedResourceClaims.model_validate(claims).claims()
        except ValidationError:
            raise OidcIdentityRejected(
                "resource token purpose or original identity mismatched"
            ) from None
