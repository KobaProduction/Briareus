"""Compose provider signature verification; never infer Platform or Cedar grants."""

import httpx
from pydantic import SecretStr

from control_panel_api.application.oidc_signing import VerifyOidcIdToken
from control_panel_api.domain.oidc_identity import (
    OidcIdentityKeysUnavailable as OidcIdentityKeysUnavailable,
)
from control_panel_api.domain.oidc_identity import OidcIdentityRejected as OidcIdentityRejected
from control_panel_api.domain.oidc_identity import VerifiedOidcIdentity as VerifiedOidcIdentity
from control_panel_api.domain.oidc_signing import IdTokenIntent
from control_panel_api.domain.oidc_signing import ProviderSigningHeader as ProviderSigningHeader
from control_panel_api.domain.oidc_signing import trusted_jwks_location as _trusted_jwks_location
from control_panel_api.infrastructure.oidc_signing import JwtOidcIdSignature
from control_panel_api.infrastructure.oidc_signing import (
    provider_signing_header as _provider_signing_header,
)
from control_panel_api.infrastructure.oidc_signing import (
    verified_provider_key as _verified_provider_key,
)

__all__ = [
    "OidcIdentityKeysUnavailable",
    "OidcIdentityRejected",
    "ProviderSigningHeader",
    "VerifiedOidcIdentity",
    "_provider_signing_header",
    "_trusted_jwks_location",
    "_verified_provider_key",
    "verify_rauthy_id_token",
]


async def verify_rauthy_id_token(
    token: SecretStr,
    *,
    expected_nonce: str,
    issuer: str,
    client_id: str,
    jwks_uri: str,
    client: httpx.AsyncClient,
) -> VerifiedOidcIdentity:
    return await VerifyOidcIdToken(JwtOidcIdSignature(client)).execute(
        token, IdTokenIntent(expected_nonce, issuer, client_id, jwks_uri)
    )
