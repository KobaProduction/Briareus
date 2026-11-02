"""SQLAlchemy/Fernet adapter; publication evidence shares the release transaction."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow
from projects._node_persistence import ModuleArtifactRow, ModuleReleaseRow
from projects.application.module_catalog import CatalogSession
from projects.domain.module_catalog import (
    ArtifactDefinition,
    CatalogError,
    Publication,
    PublicationIdentity,
    PublicationReceipt,
    PublicationReplay,
    PublishedRelease,
    ReleaseSummary,
    StoredArtifact,
)
from projects.infrastructure.audit_records import ModulePublicationAudit
from projects.infrastructure.catalog_records import InputPayload, stored_inputs
from projects.infrastructure.node_storage_models import (
    ArtifactConfigurationContract,
    ArtifactStorageContract,
)
from service_runtime.platform_db_mechanics import _DatabaseCipherBinding, _SessionCipherBinding

PUBLICATION_ACTION = "node.module.publish"


def release_summary(row: ModuleReleaseRow) -> ReleaseSummary:
    return ReleaseSummary(
        str(row.id),
        row.artifact_key,
        row.source_commit,
        row.input_fingerprint,
        row.image_reference,
        row.platform,
        row.state,
        row.created_at.isoformat(),
    )


class SqlCatalogTransactions(_DatabaseCipherBinding[PlatformDatabase, Fernet]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[CatalogSession]:
        try:
            async with self._database.transaction() as tx:
                yield SqlCatalogSession(tx, self._cipher)
        except IntegrityError:
            raise CatalogError("Release or publication operation already exists") from None


class SqlCatalogSession(_SessionCipherBinding[AsyncSession, Fernet]):
    async def releases(self, keys: tuple[str, ...]) -> tuple[ReleaseSummary, ...]:
        rows = await self._session.scalars(
            select(ModuleReleaseRow)
            .where(ModuleReleaseRow.state == "published", ModuleReleaseRow.artifact_key.in_(keys))
            .order_by(ModuleReleaseRow.created_at.desc())
            .limit(100)
        )
        return tuple(release_summary(row) for row in rows)

    async def receipt(self, operation_uuid: UUID) -> PublicationReceipt | None:
        row = await self._session.scalar(
            select(OwnerCommandRow).where(
                OwnerCommandRow.operation_uuid == operation_uuid,
                OwnerCommandRow.operation == PUBLICATION_ACTION,
            )
        )
        if row is None:
            return None
        return PublicationReceipt(
            row.actor_scope, row.project_scope, row.fingerprint, row.state, row.encrypted_outcome
        )

    def replay(self, receipt: PublicationReceipt) -> PublicationReplay:
        if receipt.encrypted_outcome is None:
            raise ValueError("Completed publication has no durable outcome")
        plaintext = self._cipher.decrypt(receipt.encrypted_outcome.encode())
        return TypeAdapter(PublicationReplay).validate_json(plaintext)

    async def artifact(self, key: str) -> StoredArtifact | None:
        row = await self._session.get(ModuleArtifactRow, key, with_for_update=True)
        if row is None:
            return None
        return StoredArtifact(row.key, row.enabled, stored_inputs(row.inputs))

    async def add_artifact(self, definition: ArtifactDefinition) -> None:
        self._session.add(
            ModuleArtifactRow(
                key=definition.key,
                name=definition.name,
                inputs=InputPayload.from_record(definition.inputs),
                configuration_contract=ArtifactConfigurationContract(kind="approved_node_adapter"),
                storage_contract=ArtifactStorageContract(
                    workspace=definition.workspace,
                    purpose=definition.storage_purpose,
                    retention="persistent",
                ),
                enabled=True,
            )
        )
        await self._session.flush()

    async def upgrade_artifact(self, definition: ArtifactDefinition) -> None:
        row = await self._session.get(ModuleArtifactRow, definition.key, with_for_update=True)
        if row is None:
            raise CatalogError("Artifact definition changed; explicit approval required")
        row.inputs = InputPayload.from_record(definition.inputs)

    async def release_exists(self, release_uuid: UUID) -> bool:
        return await self._session.get(ModuleReleaseRow, release_uuid) is not None

    async def add_release(
        self, publication: Publication, definition: ArtifactDefinition
    ) -> ReleaseSummary:
        row = ModuleReleaseRow(
            id=publication.id,
            artifact_key=publication.module,
            source_commit=publication.source_commit,
            input_fingerprint=publication.input_fingerprint,
            platform=publication.platform,
            image_reference=publication.image,
            state="published",
            storage_compatibility="workspace" if definition.workspace else "none",
        )
        self._session.add(row)
        await self._session.flush()
        return release_summary(row)

    async def complete(
        self,
        identity: PublicationIdentity,
        publication: Publication,
        result: PublishedRelease,
        upgraded: bool,
        now: datetime,
    ) -> None:
        encrypted = self._cipher.encrypt(
            json.dumps(asdict(PublicationReplay(identity.fingerprint, result))).encode()
        ).decode()
        self._session.add(
            OwnerCommandRow(
                operation_uuid=identity.operation_uuid,
                actor_scope=str(identity.actor_uuid),
                project_scope=str(identity.project_uuid),
                operation=PUBLICATION_ACTION,
                key=str(identity.operation_uuid),
                fingerprint=identity.fingerprint,
                expected_owner_revision="0",
                state="completed",
                encrypted_outcome=encrypted,
                expires_at=now + timedelta(days=7),
            )
        )
        self._session.add(
            OwnerAuditRow(
                operation_uuid=identity.operation_uuid,
                actor_user_id=identity.actor_uuid,
                project_id=identity.project_uuid,
                action=PUBLICATION_ACTION,
                object_id=str(publication.id),
                owner_revision="1",
                details=ModulePublicationAudit(
                    artifact=publication.module,
                    image=publication.image,
                    source_commit=publication.source_commit,
                    definition_upgrade=(
                        "analysis-radare2-source-closure-20261021" if upgraded else None
                    ),
                ),
            )
        )
