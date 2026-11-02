"""Publication authority, receipt scoping and rollback through the application ports."""

import unittest
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from projects.application.module_catalog import (
    CatalogSession,
    PublishModuleRelease,
    ReadModuleCatalog,
)
from projects.domain.module_catalog import (
    ArtifactDefinition,
    BuildInputs,
    CatalogError,
    LogicalModule,
    Publication,
    PublicationIdentity,
    PublicationReceipt,
    PublicationReplay,
    PublishedRelease,
    ReleaseSummary,
    ResourceLimits,
    StoredArtifact,
)


@dataclass
class MemoryState:
    artifacts: dict[str, StoredArtifact] = field(default_factory=dict)
    releases: dict[UUID, ReleaseSummary] = field(default_factory=dict)
    receipts: dict[UUID, PublicationReceipt] = field(default_factory=dict)
    outcomes: dict[str, PublicationReplay] = field(default_factory=dict)
    audits: list[tuple[PublicationIdentity, bool]] = field(default_factory=list)


@dataclass
class Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class MemorySession:
    def __init__(
        self, state: MemoryState, now: Callable[[], datetime], after_insert: Callable[[], None]
    ) -> None:
        self.state = state
        self.now = now
        self.after_insert = after_insert

    async def releases(self, keys: tuple[str, ...]) -> tuple[ReleaseSummary, ...]:
        return tuple(row for row in self.state.releases.values() if row.module in keys)

    async def receipt(self, operation_uuid: UUID) -> PublicationReceipt | None:
        return self.state.receipts.get(operation_uuid)

    def replay(self, receipt: PublicationReceipt) -> PublicationReplay:
        if receipt.encrypted_outcome is None:
            raise AssertionError("Missing durable outcome")
        return self.state.outcomes[receipt.encrypted_outcome]

    async def artifact(self, key: str) -> StoredArtifact | None:
        return self.state.artifacts.get(key)

    async def add_artifact(self, definition: ArtifactDefinition) -> None:
        self.state.artifacts[definition.key] = StoredArtifact(
            definition.key, True, definition.inputs
        )

    async def upgrade_artifact(self, definition: ArtifactDefinition) -> None:
        self.state.artifacts[definition.key] = replace(
            self.state.artifacts[definition.key], inputs=definition.inputs
        )

    async def release_exists(self, release_uuid: UUID) -> bool:
        return release_uuid in self.state.releases

    async def add_release(
        self, publication: Publication, _definition: ArtifactDefinition
    ) -> ReleaseSummary:
        row = ReleaseSummary(
            str(publication.id),
            publication.module,
            publication.source_commit,
            publication.input_fingerprint,
            publication.image,
            publication.platform,
            "published",
            self.now().isoformat(),
        )
        self.state.releases[publication.id] = row
        self.after_insert()
        return row

    async def complete(
        self,
        identity: PublicationIdentity,
        _publication: Publication,
        result: PublishedRelease,
        upgraded: bool,
        _now: datetime,
    ) -> None:
        token = str(identity.operation_uuid)
        self.state.receipts[identity.operation_uuid] = PublicationReceipt(
            str(identity.actor_uuid),
            str(identity.project_uuid),
            identity.fingerprint,
            "completed",
            token,
        )
        self.state.outcomes[token] = PublicationReplay(identity.fingerprint, result)
        self.state.audits.append((identity, upgraded))


class MemoryTransactions:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.state = MemoryState()
        self.expire_after_insert = False

    def after_insert(self) -> None:
        if self.expire_after_insert:
            self.clock.value += timedelta(minutes=1)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[CatalogSession]:
        pending = deepcopy(self.state)
        yield MemorySession(pending, self.clock.now, self.after_insert)
        self.state = pending


class CatalogUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = Clock(datetime(2026, 10, 21, tzinfo=UTC))
        self.expiry = self.clock.value + timedelta(seconds=20)
        self.transactions = MemoryTransactions(self.clock)
        self.use_case = PublishModuleRelease(self.transactions, self.clock.now)
        self.identity = PublicationIdentity(uuid4(), uuid4(), uuid4(), "f" * 64)
        self.publication = Publication(
            uuid4(),
            "files",
            "a" * 40,
            "b" * 64,
            "registry.example/files@sha256:" + "c" * 64,
            "linux/amd64",
        )
        limits = ResourceLimits(128, 200, 64)
        self.definition = ArtifactDefinition(
            "files",
            "Files",
            True,
            "stateless",
            True,
            "workspace",
            BuildInputs("hands/files/Dockerfile", ("hands/files/src/**",), "linux/amd64"),
            limits,
            limits,
        )

    async def publish(self, identity: PublicationIdentity | None = None) -> PublishedRelease:
        return await self.use_case.execute(
            identity or self.identity,
            self.publication,
            self.definition,
            ("registry.example",),
            self.expiry,
        )

    async def test_replay_preserves_exact_release_and_writes_one_audit(self) -> None:
        original = await self.publish()
        self.assertEqual(await self.publish(), original)
        self.assertEqual(len(self.transactions.state.releases), 1)
        self.assertEqual(self.transactions.state.audits, [(self.identity, False)])

    async def test_receipt_rejects_other_actor_project_or_input_before_decode(self) -> None:
        await self.publish()
        self.transactions.state.outcomes.clear()
        for changed in (
            replace(self.identity, actor_uuid=uuid4()),
            replace(self.identity, project_uuid=uuid4()),
            replace(self.identity, fingerprint="e" * 64),
        ):
            with (
                self.subTest(identity=changed),
                self.assertRaisesRegex(CatalogError, "operation conflicts"),
            ):
                await self.publish(changed)

    async def test_replay_requires_current_authority_and_matching_encrypted_fingerprint(
        self,
    ) -> None:
        original = await self.publish()
        token = str(self.identity.operation_uuid)
        self.transactions.state.outcomes[token] = PublicationReplay("d" * 64, original)
        with self.assertRaisesRegex(CatalogError, "Current publication authority"):
            await self.publish()
        self.transactions.state.outcomes[token] = PublicationReplay(
            self.identity.fingerprint, original
        )
        self.clock.value = self.expiry
        with self.assertRaisesRegex(CatalogError, "Current publication authority"):
            await self.publish()

    async def test_expiry_after_insert_rolls_back_release_artifact_receipt_and_audit(self) -> None:
        self.transactions.expire_after_insert = True
        with self.assertRaisesRegex(CatalogError, "Current Platform proof"):
            await self.publish()
        self.assertEqual(self.transactions.state, MemoryState())

    async def test_existing_release_uuid_cannot_be_republished_by_a_new_operation(self) -> None:
        await self.publish()
        with self.assertRaisesRegex(CatalogError, "identity is immutable"):
            await self.publish(replace(self.identity, operation_uuid=uuid4()))
        self.assertEqual(len(self.transactions.state.audits), 1)

    async def test_disabled_or_unreviewed_definition_cannot_publish(self) -> None:
        for artifact in (
            StoredArtifact("files", False, self.definition.inputs),
            StoredArtifact("files", True, None),
            StoredArtifact("files", True, replace(self.definition.inputs, paths=("foreign/**",))),
        ):
            with self.subTest(artifact=artifact):
                self.transactions.state.artifacts["files"] = artifact
                with self.assertRaisesRegex(CatalogError, "explicit approval"):
                    await self.publish()
                self.assertFalse(self.transactions.state.releases)

    async def test_unapproved_registry_never_enters_a_publication_transaction(self) -> None:
        with self.assertRaisesRegex(CatalogError, "registry not approved"):
            await self.use_case.execute(
                self.identity, self.publication, self.definition, (), self.expiry
            )
        self.assertEqual(self.transactions.state, MemoryState())

    async def test_reviewed_source_upgrade_keeps_existing_releases_and_build_pins(self) -> None:
        existing = await self.publish()
        added = "hands/radare2/src/radare2_hand/**"
        current = replace(
            self.definition.inputs,
            paths=("hands/reverse/src/**", added),
            build_args=(("RADARE2_IMAGE", "unchanged-digest-pin"),),
        )
        self.definition = replace(self.definition, key="reverse", inputs=current)
        self.publication = replace(self.publication, id=uuid4(), module="reverse")
        previous = replace(current, paths=("hands/reverse/src/**",))
        self.transactions.state.artifacts["reverse"] = StoredArtifact("reverse", True, previous)
        await self.publish(replace(self.identity, operation_uuid=uuid4()))
        self.assertEqual(
            self.transactions.state.releases[UUID(existing.release.id)], existing.release
        )
        self.assertEqual(self.transactions.state.artifacts["reverse"].inputs, current)
        self.assertEqual(self.transactions.state.audits[-1][1], True)

    async def test_read_catalog_requires_current_authority(self) -> None:
        await self.publish()
        read = ReadModuleCatalog(self.transactions, self.clock.now)
        modules = (LogicalModule("files", "Files", ("files",)),)
        snapshot = await read.execute((self.definition,), modules, self.expiry)
        self.assertEqual(snapshot.releases, tuple(self.transactions.state.releases.values()))
        with self.assertRaisesRegex(CatalogError, "Current Platform proof"):
            await read.execute((self.definition,), modules, self.clock.value)
