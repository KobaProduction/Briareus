"""Explicit resume preserves the original operation and consumes its request once."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from projects.application.placement_listing import PlacementOperationView
from projects.application.placement_recovery import PlacementRecoverySession, RecoverPlacement
from projects.domain.node_administration import NodeActor, NodeConflict, NodeForbidden, NodeMissing
from projects.domain.placement_admission import PlacementMutationState
from projects.domain.placement_recovery import RecoveryIntent, RecoveryReplay


class MemoryRecovery:
    def __init__(self, intent: RecoveryIntent) -> None:
        self.intent = intent
        self.target = uuid4()
        self.phase = "unknown"
        self.state = "pending"
        self.receipts: dict[UUID, RecoveryReplay] = {}
        self.resumed = 0
        self.staged = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PlacementRecoverySession]:
        snapshot = self.receipts.copy(), self.resumed, self.staged
        try:
            yield self
        except BaseException:
            self.receipts, self.resumed, self.staged = snapshot
            raise

    async def lock(self, placement_uuid: UUID, project_uuid: UUID) -> PlacementMutationState | None:
        if (placement_uuid, project_uuid) != (self.intent.placement_uuid, self.intent.project_uuid):
            return None
        return PlacementMutationState(
            placement_uuid, uuid4(), self.intent.expected_sequence, self.state
        )

    async def receipt(self, operation_uuid: UUID) -> RecoveryReplay | None:
        return self.receipts.get(operation_uuid)

    async def latest_phase(self, placement_uuid: UUID) -> str:
        if placement_uuid != self.intent.placement_uuid:
            raise AssertionError("Current placement required")
        return self.phase

    async def resume(self, intent: RecoveryIntent, actor: NodeActor) -> UUID:
        if actor.actor_uuid != intent.actor_uuid:
            raise AssertionError("Authorized actor required")
        self.receipts[intent.operation_uuid] = RecoveryReplay(
            intent.actor_uuid,
            intent.placement_uuid,
            intent.expected_sequence,
            True,
            self.target,
            intent.fingerprint,
        )
        self.resumed += 1
        return self.target

    async def stage(self, intent: RecoveryIntent, actor: NodeActor) -> None:
        if actor.actor_uuid != intent.actor_uuid:
            raise AssertionError("Authorized actor required")
        self.receipts[intent.operation_uuid] = RecoveryReplay(
            intent.actor_uuid,
            intent.placement_uuid,
            intent.expected_sequence + 1,
            True,
        )
        self.staged += 1

    async def summary(self, operation_uuid: UUID) -> PlacementOperationView:
        sequence = self.intent.expected_sequence + (operation_uuid != self.target)
        return PlacementOperationView(
            str(operation_uuid),
            str(self.intent.placement_uuid),
            sequence,
            self.phase,
            None,
            "2026-10-28T00:00:00+00:00",
            None,
        )


class ResumePlacementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 28, tzinfo=UTC)
        self.intent = RecoveryIntent(uuid4(), uuid4(), uuid4(), uuid4(), 3)
        self.actor = NodeActor(self.intent.actor_uuid, "user", self.intent.actor_uuid)
        self.store = MemoryRecovery(self.intent)
        self.recover = RecoverPlacement(self.store, lambda: 0, lambda: self.now)
        self.expiry = self.now + timedelta(seconds=30)

    async def test_resume_returns_original_operation_and_replay_never_redispatches(self) -> None:
        first = await self.recover.execute(self.intent, self.actor, self.expiry)
        replay = await self.recover.execute(self.intent, self.actor, self.expiry)
        self.assertEqual((first.operation.id, replay.operation.id), (str(self.store.target),) * 2)
        self.assertEqual(first.operation.sequence, self.intent.expected_sequence)
        self.assertTrue(first.dispatch)
        self.assertFalse(replay.dispatch)
        self.assertEqual((self.store.resumed, self.store.staged), (1, 0))

    async def test_changed_selectors_cannot_reuse_a_resume_receipt(self) -> None:
        await self.recover.execute(self.intent, self.actor, self.expiry)
        with self.assertRaises(NodeConflict):
            await self.recover.execute(
                replace(self.intent, expected_sequence=4), self.actor, self.expiry
            )
        with self.assertRaises(NodeConflict):
            await self.recover.execute(
                replace(self.intent, actor_uuid=uuid4()), self.actor, self.expiry
            )
        with self.assertRaises(NodeMissing):
            await self.recover.execute(
                replace(self.intent, project_uuid=uuid4()), self.actor, self.expiry
            )
        self.assertEqual(self.store.resumed, 1)

    async def test_expired_authority_rolls_back_resume_receipt(self) -> None:
        with self.assertRaises(NodeForbidden):
            await self.recover.execute(self.intent, self.actor, self.now)
        self.assertEqual(self.store.receipts, {})
        self.assertEqual(self.store.resumed, 0)

    async def test_terminal_recovery_keeps_its_new_operation_semantics(self) -> None:
        self.store.phase, self.store.state = "succeeded", "ready"
        first = await self.recover.execute(self.intent, self.actor, self.expiry)
        replay = await self.recover.execute(self.intent, self.actor, self.expiry)
        self.assertEqual(first.operation.id, str(self.intent.operation_uuid))
        self.assertEqual(first.operation.sequence, self.intent.expected_sequence + 1)
        self.assertTrue(first.dispatch)
        self.assertFalse(replay.dispatch)
        self.assertEqual((self.store.resumed, self.store.staged), (0, 1))
