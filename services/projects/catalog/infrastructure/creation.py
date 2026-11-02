"""Catalog-only integration creation; current owner checks stay in their local models."""

from __future__ import annotations

import hashlib
import hmac
from typing import Literal
from uuid import uuid4

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import (
    CurrentOwnerAuthorityPort,
    OwnerCommandDTO,
    OwnerProofAuthority,
    SignedOwnerProofs,
    TrustedOwnerServicePeerPort,
    VerifiedOwnerOperation,
    require_signed_payload,
)
from common.owner_transactions import OwnerCommandOutcome, OwnerLocalCommandExecutor
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from projects._provider_registry import validate_provider
from projects._resource_domain import OwnerScope, ResourceOwner, canonical_alias
from projects._resource_persistence import IntegrationRow
from projects.application.owner_receipts import CatalogCreateIntegration
from projects.catalog.application._command_payloads import (
    CREATE_INTEGRATION_PAYLOAD,
    CreateCatalogIntegrationPayload,
)
from projects.infrastructure.provider_metadata import StoredProviderSettings
from runtime_peer.domain.provider_settings import ProviderSettings
from runtime_peer.provider_settings import ProviderSettingsInput


class _CatalogCreation:
    def __init__(
        self,
        db: PlatformDatabase,
        source: OwnerProofAuthority,
        commands: OwnerLocalCommandExecutor,
        *,
        current_owners: CurrentOwnerAuthorityPort | None,
        peer_verifier: TrustedOwnerServicePeerPort | None,
        encryption_key: SecretStr,
        secret_fingerprint_key: bytes,
    ) -> None:
        if db.engine.url.database != "briareus_resources" or commands.owner != "resources":
            raise RuntimeError("Catalog service must own briareus_resources only")
        if current_owners is None or peer_verifier is None or len(secret_fingerprint_key) < 32:
            raise RuntimeError("Catalog current-owner and peer attestors are mandatory")
        self.current_owners = current_owners
        self.peer_verifier = peer_verifier
        self.cipher = Fernet(encryption_key.get_secret_value().encode())
        self._secret_fp_key = secret_fingerprint_key
        self.db = db
        self.source = source
        self.commands = commands

    @staticmethod
    def _owner_fields(
        request: OwnerCommandDTO,
        owner_scope: Literal["team", "project"],
    ) -> ResourceOwner:
        if owner_scope == "team":
            if request.expected_team_id is None:
                raise AccessDenied("Team resource requires attested Project owner Team ID")
            return ResourceOwner(OwnerScope.TEAM, request.expected_team_id)
        if owner_scope == "project":
            return ResourceOwner(OwnerScope.PROJECT, request.project_id)
        raise AccessDenied("Catalog owner scope is not authorized")

    def _secret_digest(self, secret: SecretStr) -> str:
        raw = secret.get_secret_value()
        if not 1 <= len(raw.encode()) <= 131072:
            raise InvalidInput("Catalog secret length outside protected bounds")
        # HMAC deliberately avoids persisting an unkeyed guessable password
        # hash in an original idempotent outcome or signed scope event.
        return hmac.new(self._secret_fp_key, raw.encode(), hashlib.sha256).hexdigest()

    async def create_integration(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        owner_scope: Literal["team", "project"],
        alias: str,
        provider: str,
        auth_type: str,
        provider_settings: ProviderSettings,
        credential: SecretStr,
    ) -> OwnerCommandOutcome[CatalogCreateIntegration]:
        if decision.request.operation != "catalog.integration.create":
            raise InvalidInput("unapproved Catalog integration operation")
        owner = self._owner_fields(decision.request, owner_scope)
        display, key = canonical_alias(alias)
        provider_name = provider.strip().casefold()
        auth = auth_type.strip().casefold()
        validated_settings = validate_provider(provider_name, auth, provider_settings)
        fingerprint = self._secret_digest(credential)
        require_signed_payload(
            decision.request,
            CREATE_INTEGRATION_PAYLOAD.dump_python(
                CreateCatalogIntegrationPayload(
                    owner_scope=owner_scope,
                    owner_id=str(owner.team_id or owner.project_id),
                    alias=display,
                    provider=provider_name,
                    auth_type=auth,
                    provider_settings=ProviderSettingsInput.from_record(validated_settings),
                    credential_hmac_sha256=fingerprint,
                ),
                mode="json",
            ),
        )

        async def mutation(tx: AsyncSession) -> CatalogCreateIntegration:
            active = await tx.scalar(
                select(IntegrationRow.id)
                .where(
                    IntegrationRow.owner_team_id == owner.team_id,
                    IntegrationRow.owner_project_id == owner.project_id,
                    IntegrationRow.alias_key == key,
                    IntegrationRow.deleted_at.is_(None),
                )
                .limit(1)
            )
            if active is not None:
                raise Conflict("integration alias exists within selected owner")
            row = IntegrationRow(
                id=uuid4(),
                alias=display,
                alias_key=key,
                provider=provider_name,
                auth_type=auth,
                provider_settings=StoredProviderSettings.from_record(validated_settings),
                encrypted_credential=self.cipher.encrypt(
                    credential.get_secret_value().encode()
                ).decode(),
                version=1,
                owner_team_id=owner.team_id,
                owner_project_id=owner.project_id,
            )
            tx.add(row)
            return CatalogCreateIntegration(
                resource_id=str(row.id),
                owner_scope=owner_scope,
                alias_key=key,
                version=1,
                credential_configured=True,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="catalog.integration_created",
            target=key,
            response_model=CatalogCreateIntegration,
        )
