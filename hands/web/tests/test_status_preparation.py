"""Status polls retain one preparation; foreign sessions destroy old native state."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from mcp.types import CallToolRequestParams
from supervisor_fixture import supervisor_fixture

from runtime_peer.browser_receipts import BrowserPreparingReceipt


class StatusPreparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.fixture = supervisor_fixture(self)
        self.browser, self.permit = self.fixture.browser, self.fixture.permit
        self.status = CallToolRequestParams(name="local_browser_status", arguments={})

    async def asyncTearDown(self) -> None:
        await self.browser.stop()
        await self.fixture.complete()

    async def test_pending_operation_is_visible_only_to_its_owner_without_renewing_execution(
        self,
    ) -> None:
        from mcp.types import CallToolResult

        from hand_runtime.domain.deferred_operations import DeferredRecord
        from node_protocol.effect import HumanEffectPermit
        from web_hand.infrastructure.execution_authority import execution_identity

        permit = HumanEffectPermit.model_validate(
            {
                **self.permit.model_dump(exclude={"agent_session_uuid", "grant_revision"}),
                "human": True,
                "resource_revision": 2,
            }
        )
        identity = execution_identity(permit)
        handle = self.browser.deferred.book.allocate(uuid4())
        self.browser.deferred.book.insert(
            DeferredRecord[CallToolResult](handle, identity, "local_browser_open")
        )
        reply = await self.browser.execute(self.status, permit)
        assert reply.result is not None
        pending = BrowserPreparingReceipt.model_validate(
            reply.result.structured_content
        ).result.pending
        assert pending is not None
        self.assertEqual(pending.tool, "local_browser_open")
        self.assertIn(str(handle.request_uuid), pending.operation_id)
        self.fixture.grants.assert_not_awaited()
        self.fixture.exchange.assert_not_awaited()
        with self.assertRaises(ValueError):
            await self.browser.execute(
                self.status, permit.model_copy(update={"actor_uuid": uuid4()})
            )
        self.fixture.grants.assert_not_awaited()

    async def test_warm_status_uses_renewable_preparation_instead_of_expiring_ipc(self) -> None:
        self.browser.status_warm = True
        first = await self.browser.execute(self.status, self.permit)
        assert first.result is not None
        self.assertTrue(
            BrowserPreparingReceipt.model_validate(first.result.structured_content).result.starting
        )
        await asyncio.sleep(0)
        self.fixture.exchange.assert_awaited_once_with(self.status, self.permit, startup=True)
        await self.browser.execute(self.status, self.permit)
        self.assertEqual(self.fixture.exchange.await_count, 1)
        self.fixture.finish.set()
        await asyncio.sleep(0)
        reply = await self.browser.execute(self.status, self.permit)
        assert reply.result is not None
        self.assertFalse(reply.result.is_error)
        self.assertTrue(self.browser.status_warm)

    async def test_status_polls_resume_one_preparation_other_tools_cannot_renew_it(self) -> None:
        first = await self.browser.execute(self.status, self.permit)
        assert first.result is not None
        self.assertTrue(
            BrowserPreparingReceipt.model_validate(first.result.structured_content).result.starting
        )
        await asyncio.sleep(0)
        self.assertEqual(self.fixture.exchange.await_count, 1)
        await self.browser.execute(self.status, self.permit)
        grants = self.fixture.grants.await_count
        with self.assertRaises(ValueError):
            await self.browser.execute(
                CallToolRequestParams(
                    name="local_browser_open",
                    arguments={"url": "https://example.com"},
                ),
                self.permit,
            )
        self.assertEqual(self.fixture.grants.await_count, grants)
        self.fixture.finish.set()
        task = self.browser.status_task
        assert task is not None
        await task
        ready = await self.browser.execute(self.status, self.permit)
        self.assertIsNotNone(ready.result)
        self.assertTrue(self.browser.status_warm)
        self.assertEqual(self.fixture.exchange.await_count, 1)

    async def test_other_session_destroys_old_preparation_before_starting_its_own(self) -> None:
        await self.browser.execute(self.status, self.permit)
        await asyncio.sleep(0)
        old = self.browser.status_task
        assert old is not None
        other = self.permit.model_copy(update={"agent_session_uuid": uuid4()})
        await self.browser.execute(self.status, other)
        warming = self.browser.warming_task
        assert warming is not None
        await warming
        self.assertTrue(old.cancelled())
        self.fixture.stop.assert_awaited_once()
        self.fixture.start.assert_awaited_once()
        self.assertEqual(self.fixture.grants.await_count, 1)
        await self.browser.execute(self.status, other)
        self.assertEqual(
            self.fixture.grants.call_args.args[0],
            (str(other.actor_uuid), str(other.agent_session_uuid), other.grant_revision),
        )

    async def test_background_failure_stops_runtime_when_status_is_consumed(self) -> None:
        self.fixture.exchange.side_effect = ValueError("private startup failure")
        await self.browser.execute(self.status, self.permit)
        await asyncio.sleep(0)
        with self.assertRaises(ValueError):
            await self.browser.execute(self.status, self.permit)
        self.fixture.stop.assert_awaited_once()
        self.assertIsNone(self.browser.status_task)

    async def test_metadata_recovery_is_bounded_and_never_executes_a_tool(self) -> None:
        self.fixture.start.side_effect = ValueError("metadata unavailable")
        with patch("web_hand.node_supervisor.asyncio.sleep", AsyncMock()):
            await self.browser.warm_profile(self.browser.profile_key)
        self.assertEqual(self.fixture.start.await_count, 3)
        self.fixture.exchange.assert_not_awaited()

    async def test_status_does_not_wait_for_metadata_replacement_lock(self) -> None:
        entered, finish = asyncio.Event(), asyncio.Event()

        async def slow_start(_key: str | None) -> None:
            entered.set()
            await finish.wait()

        self.fixture.start.side_effect = slow_start
        self.fixture.stop.side_effect = None
        self.browser.prepare_profile(self.browser.profile_key)
        warming = self.browser.warming_task
        assert warming is not None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertTrue(self.browser.lock.locked())
            reply = await asyncio.wait_for(self.browser.execute(self.status, self.permit), 0.2)
            assert reply.result is not None
            self.assertTrue(
                BrowserPreparingReceipt.model_validate(
                    reply.result.structured_content
                ).result.starting
            )
            self.fixture.grants.assert_not_awaited()
            self.fixture.exchange.assert_not_awaited()
        finally:
            finish.set()
            await warming
