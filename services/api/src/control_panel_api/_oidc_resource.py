"""Compose verification of a provider resource bearer bound to the original identity."""

from datetime import UTC, datetime
from functools import partial

import httpx
from pydantic import SecretStr

from control_panel_api._oidc_origin_policy import (
    RESOURCE_BROKER_CLIENT_ID,
    validate_broker_resource_intent,
    validate_files_resource_intent,
)
from control_panel_api.application.oidc_signing_resource import VerifyOidcResource
from control_panel_api.domain.oidc_identity import (
    PrivateOidcResourceCredential as PrivateOidcResourceCredential,
)
from control_panel_api.domain.oidc_identity import VerifiedOidcIdentity
from control_panel_api.domain.oidc_signing_resource import ResourceTokenIntent
from control_panel_api.infrastructure.oidc_signing_resource import JwtOidcResourceSignature

_utc_now = partial(datetime.now, UTC)


async def verify_resource_credential(
    *,
    token: SecretStr,
    identity: VerifiedOidcIdentity,
    resource_audience: str,
    token_deadline: datetime,
    jwks_uri: str,
    client: httpx.AsyncClient,
    token_client_id: str | None = None,
) -> PrivateOidcResourceCredential:
    if token_client_id is None:
        validate_files_resource_intent(
            issuer=identity.issuer,
            client_id=identity.client_id,
            resource_audience=resource_audience,
        )
    else:
        if token_client_id != RESOURCE_BROKER_CLIENT_ID:
            raise ValueError("Pinned confidential resource client required")
        validate_broker_resource_intent(
            issuer=identity.issuer, client_id=identity.client_id, audience=resource_audience
        )
    return await VerifyOidcResource(JwtOidcResourceSignature(client), _utc_now).execute(
        token,
        ResourceTokenIntent(identity, resource_audience, token_deadline, jwks_uri, token_client_id),
    )
