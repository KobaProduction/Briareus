"""Explicit disposable PostgreSQL fixture; normal service configuration is never read."""

import base64
import os
import time
import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from projects._node_persistence import ModuleArtifactRow, NodeModuleRow, NodeOperationRow, NodeRow
from projects.infrastructure.catalog_records import InputPayload, artifact_definition
from projects.infrastructure.node_journal import SqlNodeJournal
from projects.infrastructure.node_storage_models import (
    ArtifactConfigurationContract,
    ArtifactStorageContract,
)

from common.platform_db import PlatformDatabase, PlatformDatabaseSettings
from node_protocol import (
    Deployment,
    ModuleRelease,
    NodeBudget,
    NodeRecord,
    NodeScope,
    ResourceLimits,
)
from node_protocol.catalog import ARTIFACTS
from node_protocol.control import ControlCommand
from node_protocol.journal import (
    AcquireJournal,
    JournalAction,
    JournalRequest,
    JournalResult,
    ReserveOperation,
    SignedJournalRequest,
    sign_request,
)


def pem(key: Ed25519PrivateKey) -> str:
    return (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


class JournalPgFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        if os.environ.get("NODE_JOURNAL_PG_ACCEPTANCE") != "1":
            self.skipTest("Explicit disposable Resources PostgreSQL acceptance required")
        self.settings = PlatformDatabaseSettings.model_validate(
            {
                "POSTGRES_HOST": os.environ["JOURNAL_TEST_POSTGRES_HOST"],
                "POSTGRES_PORT": int(os.environ["JOURNAL_TEST_POSTGRES_PORT"]),
                "POSTGRES_DB": os.environ["JOURNAL_TEST_POSTGRES_DB"],
                "POSTGRES_USER": os.environ["JOURNAL_TEST_POSTGRES_USER"],
                "POSTGRES_PASSWORD": os.environ["JOURNAL_TEST_POSTGRES_PASSWORD"],
            }
        )
        if (
            self.settings.postgres_host != "briareus-node-schema-audit"
            or self.settings.postgres_db != "briareus_resources"
        ):
            raise RuntimeError("Refusing non-disposable Resources database")
        self.database = PlatformDatabase(self.settings)
        self.core = Ed25519PrivateKey.generate()
        self.node_key = Ed25519PrivateKey.generate()
        self.gateway = Ed25519PrivateKey.generate()
        self.api = SqlNodeJournal(self.database, self.core.public_key(), self.gateway.public_key())
        self.node_uuid, self.project_uuid, self.actor_uuid = uuid4(), uuid4(), uuid4()
        self.session = uuid4()
        self.epoch: int | None = None
        self.record = NodeRecord(
            id=self.node_uuid,
            name="journal-acceptance",
            scope=NodeScope(kind="shared"),
            budget=NodeBudget(
                total=ResourceLimits(memory_bytes=1024**3, cpu_millis=2000, pids=512),
                reserved=ResourceLimits(memory_bytes=384 * 1024**2, cpu_millis=750, pids=192),
            ),
            enabled=True,
            created_at=datetime.now(UTC),
        )
        async with self.database.transaction() as tx:
            tx.add(
                NodeRow(
                    id=self.node_uuid,
                    name=self.record.name,
                    scope="shared",
                    owner_uuid=None,
                    host_uuid=uuid4(),
                    runtime_uid=2001,
                    endpoint="https://journal-node.example",
                    public_key=pem(self.node_key),
                    budget=self.record.budget,
                    enabled=True,
                    sequence=1,
                    created_at=self.record.created_at,
                )
            )
        acquired = await self.call(AcquireJournal())
        self.epoch = acquired.lease_epoch
        self.assertIsNotNone(self.epoch)

    async def asyncTearDown(self) -> None:
        if hasattr(self, "database"):
            await self.database.close()

    def envelope(
        self, payload: JournalAction, *, session: UUID | None = None, epoch: int | None = None
    ) -> SignedJournalRequest:
        now = int(time.time())
        request = JournalRequest(
            node_uuid=self.node_uuid,
            request_uuid=uuid4(),
            session_uuid=session or self.session,
            lease_epoch=None if isinstance(payload, AcquireJournal) else epoch or self.epoch,
            issued_at=now,
            expires_at=now + 15,
            payload=payload,
        )
        return sign_request(request, self.node_key)

    async def call(self, payload: JournalAction) -> JournalResult:
        return await self.api.execute(self.envelope(payload), now=int(time.time()))

    def spec(self, *, placement: UUID | None = None, cpu: int = 200) -> Deployment:
        return Deployment(
            id=placement or uuid4(),
            node_uuid=self.node_uuid,
            project_uuid=self.project_uuid,
            release=ModuleRelease(
                module="svc",
                image="registry.example/svc@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
            limits=ResourceLimits(memory_bytes=64 * 1024**2, cpu_millis=cpu, pids=64),
        )

    def command(
        self,
        action: str,
        *,
        operation: UUID,
        sequence: int,
        desired: Deployment | None = None,
        record: NodeRecord | None = None,
    ) -> ControlCommand:
        now = int(time.time())
        return ControlCommand.model_validate(
            {
                "node_uuid": self.node_uuid,
                "operation_uuid": operation,
                "action": action,
                "sequence": sequence,
                "issued_at": now,
                "expires_at": now + 20,
                "deployment": desired,
                "node_record": record,
            }
        )

    def signature(self, command: ControlCommand) -> str:
        return base64.b64encode(self.core.sign(command.signing_bytes())).decode()

    async def intent(self, desired: Deployment, sequence: int) -> ReserveOperation:
        operation = uuid4()
        async with self.database.transaction() as tx:
            if await tx.get(ModuleArtifactRow, "svc") is None:
                tx.add(
                    ModuleArtifactRow(
                        key="svc",
                        name="Service",
                        inputs=InputPayload.from_record(
                            artifact_definition(ARTIFACTS["svc"]).inputs
                        ),
                        configuration_contract=ArtifactConfigurationContract(
                            kind="approved_node_adapter"
                        ),
                        storage_contract=ArtifactStorageContract(workspace=True, purpose="svc"),
                        enabled=True,
                    )
                )
                await tx.flush()
            placement = await tx.get(NodeModuleRow, desired.id)
            if placement is None:
                placement = NodeModuleRow(
                    id=desired.id,
                    node_uuid=self.node_uuid,
                    project_uuid=self.project_uuid,
                    artifact_key="svc",
                    name="journal-test",
                    limits=desired.limits,
                    state="pending",
                    sequence=sequence,
                )
                tx.add(placement)
                await tx.flush()
            else:
                placement.sequence = sequence
            tx.add(
                NodeOperationRow(
                    id=operation,
                    node_uuid=self.node_uuid,
                    placement_uuid=desired.id,
                    actor_uuid=self.actor_uuid,
                    sequence=sequence,
                    fingerprint=desired.fingerprint,
                    desired=desired,
                    previous=None,
                    phase="queued",
                )
            )
        command = self.command("apply", operation=operation, sequence=sequence, desired=desired)
        return ReserveOperation(core_command=command, core_signature=self.signature(command))

    async def complete_intent(self, operation: UUID, *, phase: str = "succeeded") -> None:
        async with self.database.transaction() as tx:
            row = await tx.get(NodeOperationRow, operation)
            if row is None:
                self.fail("Core intent must exist")
            row.phase = phase

    async def reconnect(self) -> None:
        await self.database.close()
        self.database = PlatformDatabase(self.settings)
        self.api = SqlNodeJournal(self.database, self.core.public_key(), self.gateway.public_key())
