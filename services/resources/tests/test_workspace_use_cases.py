"""Workspace identity and proof expiry are enforced before transaction completion."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from projects.application.project_workspaces import (
    ProjectWorkspaces,
    WorkspaceReceipt,
    WorkspaceSession,
)
from projects.domain.project_workspaces import (
    ProjectWorkspace,
    WorkspaceActor,
    WorkspaceIdentity,
    WorkspaceNode,
    WorkspaceRejected,
    WorkspaceReplay,
)


class MemoryWorkspaces:
    def __init__(self, identity: WorkspaceIdentity) -> None:
        self.node = WorkspaceNode(
            identity.node_uuid, "personal", identity.actor_uuid, True, False, True
        )
        self.current: ProjectWorkspace | None = None
        self.saved_receipt: WorkspaceReceipt | None = None
        self.saved_replay: WorkspaceReplay | None = None
        self.creations = 0
        self.completions = 0
        self.inside = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[WorkspaceSession]:
        original = (
            self.current,
            self.saved_receipt,
            self.saved_replay,
            self.creations,
            self.completions,
        )
        self.inside = True
        try:
            yield self
        except BaseException:
            (
                self.current,
                self.saved_receipt,
                self.saved_replay,
                self.creations,
                self.completions,
            ) = original
            raise
        finally:
            self.inside = False

    async def lock_node(self, identity: WorkspaceIdentity) -> WorkspaceNode | None:
        if not self.inside:
            raise AssertionError("Node lock must be inside workspace transaction")
        return self.node if self.node.node_uuid == identity.node_uuid else None

    async def workspace(self, identity: WorkspaceIdentity) -> ProjectWorkspace | None:
        if self.current is not None and (self.current.node_uuid, self.current.project_uuid) != (
            identity.node_uuid,
            identity.project_uuid,
        ):
            return None
        return self.current

    async def receipt(self, identity: WorkspaceIdentity) -> WorkspaceReceipt | None:
        if self.saved_replay is None or self.saved_replay.operation != str(identity.operation_uuid):
            return None
        return self.saved_receipt

    def replay(self, receipt: WorkspaceReceipt) -> WorkspaceReplay:
        if self.saved_replay is None or receipt != self.saved_receipt:
            raise AssertionError("No replay saved")
        return self.saved_replay

    async def create(self, identity: WorkspaceIdentity) -> ProjectWorkspace:
        self.creations += 1
        self.current = ProjectWorkspace(
            uuid4(), identity.node_uuid, identity.project_uuid, "workspace", "persistent"
        )
        return self.current

    async def complete(
        self, identity: WorkspaceIdentity, workspace: ProjectWorkspace, now: datetime
    ) -> None:
        if now.tzinfo is None:
            raise AssertionError("Receipt completion needs an aware timestamp")
        self.completions += 1
        self.saved_receipt = WorkspaceReceipt(
            str(identity.actor_uuid),
            str(identity.project_uuid),
            identity.fingerprint,
            "completed",
            "sealed",
        )
        self.saved_replay = WorkspaceReplay(
            str(identity.operation_uuid), identity.fingerprint, workspace
        )


class WorkspaceUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 21, tzinfo=UTC)
        self.identity = WorkspaceIdentity(uuid4(), uuid4(), uuid4(), uuid4(), "digest")
        self.actor = WorkspaceActor(self.identity.actor_uuid, "user", str(self.identity.actor_uuid))
        self.storage = MemoryWorkspaces(self.identity)
        self.use_case = ProjectWorkspaces(self.storage, lambda: self.now)

    async def test_ensure_replay_and_listing_share_one_storage_without_duplicate_audit(
        self,
    ) -> None:
        first = await self.use_case.execute(
            self.identity, self.actor, ensure=True, expiry=self.now + timedelta(seconds=10)
        )
        replay = await self.use_case.execute(
            self.identity, self.actor, ensure=True, expiry=self.now + timedelta(seconds=10)
        )
        listing = await self.use_case.execute(
            self.identity, self.actor, ensure=False, expiry=self.now + timedelta(seconds=10)
        )
        self.assertEqual(first, replay)
        self.assertEqual(listing.workspace, first.workspace)
        self.assertFalse(listing.ensured)
        self.assertEqual((self.storage.creations, self.storage.completions), (1, 1))

    async def test_expiry_rolls_back_creation_and_receipt_together(self) -> None:
        with self.assertRaisesRegex(WorkspaceRejected, "Current Platform proof required"):
            await self.use_case.execute(self.identity, self.actor, ensure=True, expiry=self.now)
        self.assertIsNone(self.storage.current)
        self.assertIsNone(self.storage.saved_receipt)
        self.assertEqual((self.storage.creations, self.storage.completions), (0, 0))

    async def test_replay_rejects_changed_actor_and_current_storage(self) -> None:
        await self.use_case.execute(
            self.identity, self.actor, ensure=True, expiry=self.now + timedelta(seconds=10)
        )
        with self.assertRaisesRegex(WorkspaceRejected, "Workspace operation identity conflicts"):
            await self.use_case.execute(
                replace(self.identity, actor_uuid=uuid4()),
                self.actor,
                ensure=True,
                expiry=self.now + timedelta(seconds=10),
            )
        if self.storage.current is None:
            self.fail("Workspace must exist after successful ensure")
        self.storage.current = replace(self.storage.current, id=uuid4())
        with self.assertRaisesRegex(WorkspaceRejected, "Current workspace receipt unavailable"):
            await self.use_case.execute(
                self.identity, self.actor, ensure=True, expiry=self.now + timedelta(seconds=10)
            )

    async def test_current_node_ownership_is_required_even_for_listing(self) -> None:
        self.storage.node = replace(self.storage.node, owner_uuid=uuid4())
        with self.assertRaises(WorkspaceRejected) as failure:
            await self.use_case.execute(
                self.identity, self.actor, ensure=False, expiry=self.now + timedelta(seconds=10)
            )
        self.assertTrue(failure.exception.forbidden)
        self.assertEqual(self.storage.creations, 0)
