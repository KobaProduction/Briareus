"""Publish with one atomic owner receipt/audit transaction and current authority."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.application._transaction_binding import _TransactionClockBinding
from projects.domain.module_catalog import (
    ArtifactDefinition,
    CatalogError,
    LogicalModule,
    Publication,
    PublicationIdentity,
    PublicationReceipt,
    PublicationReplay,
    PublishedRelease,
    ReleaseSummary,
    StoredArtifact,
    require_approved_artifact,
    require_publishable,
)


class CatalogSession(Protocol):
    async def releases(self, keys: tuple[str, ...]) -> tuple[ReleaseSummary, ...]: ...
    async def receipt(self, operation_uuid: UUID) -> PublicationReceipt | None: ...
    def replay(self, receipt: PublicationReceipt) -> PublicationReplay: ...
    async def artifact(self, key: str) -> StoredArtifact | None: ...
    async def add_artifact(self, definition: ArtifactDefinition) -> None: ...
    async def upgrade_artifact(self, definition: ArtifactDefinition) -> None: ...
    async def release_exists(self, release_uuid: UUID) -> bool: ...
    async def add_release(
        self, publication: Publication, definition: ArtifactDefinition
    ) -> ReleaseSummary: ...
    async def complete(
        self,
        identity: PublicationIdentity,
        publication: Publication,
        result: PublishedRelease,
        upgraded: bool,
        now: datetime,
    ) -> None: ...


class CatalogTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[CatalogSession]: ...


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    modules: tuple[LogicalModule, ...]
    artifacts: tuple[ArtifactDefinition, ...]
    releases: tuple[ReleaseSummary, ...]


class ReadModuleCatalog(_TransactionClockBinding[CatalogTransactions]):
    async def execute(
        self,
        definitions: tuple[ArtifactDefinition, ...],
        modules: tuple[LogicalModule, ...],
        expiry: datetime,
    ) -> CatalogSnapshot:
        async with self._transactions.transaction() as session:
            releases = await session.releases(tuple(item.key for item in definitions))
            require_current(expiry, self._now())
            return CatalogSnapshot(modules, definitions, releases)


class PublishModuleRelease(_TransactionClockBinding[CatalogTransactions]):
    async def execute(
        self,
        identity: PublicationIdentity,
        publication: Publication,
        definition: ArtifactDefinition,
        registries: tuple[str, ...],
        expiry: datetime,
    ) -> PublishedRelease:
        require_publishable(definition, publication, registries)
        async with self._transactions.transaction() as session:
            receipt = await session.receipt(identity.operation_uuid)
            if receipt is not None:
                return self._replay(session, receipt, identity, expiry)
            upgraded = await prepare_artifact(session, definition)
            if await session.release_exists(publication.id):
                raise CatalogError("Published release identity is immutable")
            result = PublishedRelease(await session.add_release(publication, definition))
            require_current(expiry, self._now())
            await session.complete(identity, publication, result, upgraded, self._now())
        return result

    def _replay(
        self,
        session: CatalogSession,
        receipt: PublicationReceipt,
        identity: PublicationIdentity,
        expiry: datetime,
    ) -> PublishedRelease:
        receipt.require_matches(identity)
        replay = session.replay(receipt)
        if replay.fingerprint != identity.fingerprint or expiry <= self._now():
            raise CatalogError("Current publication authority required")
        return replay.result


async def prepare_artifact(session: CatalogSession, definition: ArtifactDefinition) -> bool:
    artifact = await session.artifact(definition.key)
    if artifact is None:
        await session.add_artifact(definition)
        return False
    upgraded = require_approved_artifact(artifact, definition)
    if upgraded:
        await session.upgrade_artifact(definition)
    return upgraded


def require_current(expiry: datetime, now: datetime) -> None:
    if expiry <= now:
        raise CatalogError("Current Platform proof required")
