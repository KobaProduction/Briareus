"""ZITADEL adapter for the existing resource-bound MCP OAuth facade."""

from __future__ import annotations

import asyncio
import hashlib

from briareus_identity.identity_provider import IdentityProviderError, ZitadelClient
from briareus_identity.identity_settings import McpAuthSettings
from cryptography.fernet import Fernet
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper


class ZitadelTokenVerifier(TokenVerifier):
    def __init__(self, provider: ZitadelClient) -> None:
        super().__init__(required_scopes=["openid"])
        self.provider = provider

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            identity = await asyncio.to_thread(self.provider.introspect, token)
        except IdentityProviderError:
            return None
        return AccessToken(
            token=token,
            client_id=identity.client_id,
            scopes=identity.scope.split(),
            expires_at=identity.exp,
            subject=identity.sub,
            claims=identity.model_dump(mode="json"),
        )


def oauth_storage(settings: McpAuthSettings) -> AsyncKeyValue:
    signing_key = derive_jwt_key(
        low_entropy_material=settings.resolved_signing_key,
        salt="fastmcp-jwt-signing-key",
    )
    encryption_key = derive_jwt_key(
        high_entropy_material=signing_key.decode(),
        salt="fastmcp-storage-encryption-key",
    )
    fingerprint = hashlib.sha256(encryption_key).hexdigest()[:12]
    directory = settings.state_directory / fingerprint
    directory.mkdir(parents=True, exist_ok=True)
    store = FileTreeStore(
        data_directory=directory,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(directory),
    )
    return FernetEncryptionWrapper(
        key_value=store,
        fernet=Fernet(encryption_key),
        raise_on_decryption_error=True,
    )
