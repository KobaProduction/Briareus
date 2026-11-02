"""Rauthy 0.37.1 RFC8693 access-token exchange; never an identity/grant issuer.

Source: rauthy@ce35a70fbc43203b1a6910d3db30389228825f46,
src/service/src/oidc/grant_types/token_exchange.rs and token_set.rs.
The exchange secret stays in Core. Resource bearers stay in private escrow
until used on the authenticated dataplane; browser JSON never contains them.
"""

import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from control_panel_api._oidc import RauthyOidcAdapter

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from control_panel_api.domain.resource_escrow import (
    ResourceCredentialUnavailable as ResourceCredentialUnavailable,
)

from ._oidc_id_token import OidcIdentityRejected, VerifiedOidcIdentity
from ._oidc_origin_policy import RESOURCE_BROKER_CLIENT_ID, mcp_resource_audience
from ._oidc_resource import PrivateOidcResourceCredential, verify_resource_credential

GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
RFC8693_RESOURCE_KIND = "urn:ietf:params:oauth:token-type:access_token"


class ResourceBrokerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)
    client_id: Literal["briareus-resource-broker"]
    client_secret: SecretStr = Field(min_length=32, max_length=512)


class _ProviderSubject(BaseModel):
    sub: str | None = None


class _TokenReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    access_token: SecretStr = Field(min_length=80, max_length=8192)
    token_type: Literal["Bearer"]
    expires_in: int = Field(ge=1, le=300)
    scope: str | None = Field(default=None, max_length=512)
    # Pinned Rauthy TokenSet omits this RFC field. If added, only access tokens qualify.
    issued_token_type: Literal["urn:ietf:params:oauth:token-type:access_token"] | None = None


class ResourceTokenBroker:
    def __init__(self, *, provider: "RauthyOidcAdapter", settings: ResourceBrokerSettings) -> None:
        mcp_resource_audience(issuer=provider.issuer, client_id=provider.client_id, hand="files")
        self.provider, self.settings = provider, settings

    @classmethod
    def from_environment(cls, provider: "RauthyOidcAdapter") -> "ResourceTokenBroker | None":
        path = os.environ.get("OIDC_RESOURCE_BROKER_FILE")
        if not path:
            return None
        try:
            raw = Path(path).read_bytes()
            if len(raw) > 4096:
                raise ValueError
            return cls(provider=provider, settings=ResourceBrokerSettings.model_validate_json(raw))
        except (OSError, ValueError):
            raise ResourceCredentialUnavailable("Invalid resource broker configuration") from None

    async def exchange(
        self, *, source: PrivateOidcResourceCredential, identity: VerifiedOidcIdentity, hand: str
    ) -> PrivateOidcResourceCredential:
        provider = self.provider
        audience = mcp_resource_audience(
            issuer=provider.issuer, client_id=provider.client_id, hand=hand
        )
        primary = mcp_resource_audience(
            issuer=provider.issuer, client_id=provider.client_id, hand="files"
        )
        if (
            source.issuer.rstrip("/") != provider.issuer.rstrip("/")
            or source.subject != identity.subject
            or source.client_id != provider.client_id
            or source.audience != primary
            or identity.issuer.rstrip("/") != provider.issuer.rstrip("/")
            or identity.client_id != provider.client_id
            or min(identity.expires_at, source.expires_at) <= datetime.now(UTC)
        ):
            raise OidcIdentityRejected("Current primary Rauthy credential required")
        try:
            metadata = await provider.discovery()
            if GRANT not in metadata.grant_types_supported:
                raise ResourceCredentialUnavailable("Pinned Rauthy exchange unavailable")
            await verify_resource_credential(
                token=SecretStr(source.bearer.get_secret_value()),
                identity=identity,
                resource_audience=primary,
                token_deadline=source.expires_at,
                jwks_uri=metadata.jwks_uri,
                client=provider._client,
            )
            if not metadata.userinfo_endpoint:
                raise ResourceCredentialUnavailable("Current provider identity unavailable")
            current = await provider._client.get(
                metadata.userinfo_endpoint,
                headers={
                    "Authorization": "Bearer " + source.bearer.get_secret_value(),
                    "Accept": "application/json",
                },
            )
            if current.status_code in {401, 403}:
                raise OidcIdentityRejected("Provider rejected current primary credential")
            if (
                current.status_code != 200
                or len(current.content) > 65536
                or current.headers.get("content-type", "").split(";", 1)[0] != "application/json"
            ):
                raise ResourceCredentialUnavailable("Provider identity unavailable")
            from control_panel_api.infrastructure.json_fields import validate_unique_fields

            validate_unique_fields(current.content)
            if _ProviderSubject.model_validate_json(current.content).sub != identity.subject:
                raise OidcIdentityRejected("Provider identity changed")
            began = datetime.now(UTC)
            response = await provider._client.post(
                metadata.token_endpoint,
                data={
                    "grant_type": GRANT,
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret.get_secret_value(),
                    "subject_token": source.bearer.get_secret_value(),
                    "subject_token_type": RFC8693_RESOURCE_KIND,
                    "requested_token_type": RFC8693_RESOURCE_KIND,
                    "resource": audience,
                },
                headers={"Accept": "application/json"},
            )
            if (
                response.status_code != 200
                or len(response.content) > 65536
                or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
            ):
                logging.getLogger(__name__).warning(
                    "Resource token exchange unavailable hand=%s status=%s",
                    hand,
                    response.status_code,
                )
                raise ResourceCredentialUnavailable("Provider resource exchange unavailable")
            validate_unique_fields(response.content)
            reply = _TokenReply.model_validate_json(response.content)
            return await verify_resource_credential(
                token=reply.access_token,
                identity=identity,
                resource_audience=audience,
                token_deadline=min(source.expires_at, began + timedelta(seconds=reply.expires_in)),
                jwks_uri=metadata.jwks_uri,
                client=provider._client,
                token_client_id=RESOURCE_BROKER_CLIENT_ID,
            )
        except OidcIdentityRejected:
            raise
        except Exception as error:
            logging.getLogger(__name__).warning(
                "Resource credential unavailable hand=%s error_type=%s", hand, type(error).__name__
            )
            raise ResourceCredentialUnavailable(
                "Verified Rauthy resource exchange unavailable"
            ) from None
