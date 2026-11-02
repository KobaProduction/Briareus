"""Runtime override replay still requires a fresh proof and one atomic owner transaction."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from projects.application.runtime_settings import (
    ManageRuntimeSettings,
    RuntimePolicyReceipt,
    RuntimeSettingsSession,
)
from projects.domain.runtime_settings import (
    RuntimeOverride,
    RuntimeOverrides,
    RuntimePolicyForbidden,
    RuntimePolicyIdentity,
    RuntimePolicyView,
    RuntimeSetting,
    StoredRuntimePolicy,
)


class MemoryRuntimeSettings:
    def __init__(self) -> None:
        self.policies: dict[str, StoredRuntimePolicy] = {}
        self.receipts: dict[UUID, RuntimePolicyReceipt] = {}
        self.outcomes: dict[RuntimePolicyReceipt, RuntimePolicyView] = {}
        self.locked: str | None = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[RuntimeSettingsSession]:
        original = (self.policies.copy(), self.receipts.copy(), self.outcomes.copy())
        try:
            yield self
        except BaseException:
            self.policies, self.receipts, self.outcomes = original
            raise
        finally:
            self.locked = None

    async def lock(self, key: str) -> StoredRuntimePolicy | None:
        self.locked = key
        return self.policies.get(key)

    async def node_exists(self, node_uuid: UUID) -> bool:
        return node_uuid.version == 4

    async def get(self, key: str) -> StoredRuntimePolicy | None:
        return self.policies.get(key)

    async def receipt(self, operation_uuid: UUID) -> RuntimePolicyReceipt | None:
        return self.receipts.get(operation_uuid)

    def replay(self, receipt: RuntimePolicyReceipt) -> RuntimePolicyView:
        return self.outcomes[receipt]

    async def save(self, key: str, policy: StoredRuntimePolicy) -> None:
        if self.locked != key:
            raise AssertionError("Policy writes require the canonical scope lock")
        self.policies[key] = policy

    async def complete(
        self, identity: RuntimePolicyIdentity, key: str, view: RuntimePolicyView, now: datetime
    ) -> None:
        if self.locked != key or now.tzinfo is None:
            raise AssertionError("Receipt and policy need the same current transaction")
        receipt = RuntimePolicyReceipt(
            identity.fingerprint, str(identity.actor_uuid), str(identity.project_uuid), "sealed"
        )
        self.receipts[identity.operation_uuid] = receipt
        self.outcomes[receipt] = view


class RuntimeSettingsUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 21, tzinfo=UTC)
        self.identity = RuntimePolicyIdentity(uuid4(), uuid4(), uuid4(), "digest", 0)
        self.store = MemoryRuntimeSettings()
        self.use_case = ManageRuntimeSettings(self.store, lambda: self.now)

    async def test_empty_overrides_still_write_and_replay_never_rewrites_policy(self) -> None:
        first = await self.use_case.execute(
            self.identity,
            scope="server",
            node_uuid=None,
            overrides=RuntimeOverrides(),
            expiry=self.now + timedelta(seconds=10),
        )
        replay = await self.use_case.execute(
            self.identity,
            scope="server",
            node_uuid=None,
            overrides=RuntimeOverrides(),
            expiry=self.now + timedelta(seconds=10),
        )
        self.assertEqual(first, replay)
        self.assertEqual(first.sequence, 1)
        self.assertEqual(len(self.store.receipts), 1)
        self.assertEqual(self.store.policies["server"].sequence, 1)

    async def test_expired_replay_cannot_use_a_durable_outcome_as_authority(self) -> None:
        await self.use_case.execute(
            self.identity,
            scope="server",
            node_uuid=None,
            overrides=RuntimeOverrides(),
            expiry=self.now + timedelta(seconds=10),
        )
        with self.assertRaises(RuntimePolicyForbidden):
            await self.use_case.execute(
                self.identity,
                scope="server",
                node_uuid=None,
                overrides=RuntimeOverrides(),
                expiry=self.now,
            )
        self.assertEqual(self.store.policies["server"].sequence, 1)

    async def test_expiry_rolls_back_override_receipt_and_revision_together(self) -> None:
        overrides = RuntimeOverrides((RuntimeOverride(RuntimeSetting.EXECUTION_TIMEOUT, None),))
        with self.assertRaises(RuntimePolicyForbidden):
            await self.use_case.execute(
                self.identity, scope="server", node_uuid=None, overrides=overrides, expiry=self.now
            )
        self.assertFalse(self.store.policies)
        self.assertFalse(self.store.receipts)
        self.assertFalse(self.store.outcomes)
