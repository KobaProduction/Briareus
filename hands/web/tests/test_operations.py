"""Exact current original-tool authority alone resumes a deferred browser effect."""

import unittest

from mcp.types import CallToolRequestParams
from supervisor_fixture import operation, supervisor_fixture

from hand_runtime.domain.deferred_operations import OperationState
from node_protocol.effect import NodeEffectPermit
from runtime_peer.browser_receipts import BrowserPreparingReceipt


class WebOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.fixture = supervisor_fixture(self, warm=True)
        self.browser, self.permit = self.fixture.browser, self.fixture.permit
        self.identity = (
            str(self.permit.actor_uuid),
            str(self.permit.agent_session_uuid),
            self.permit.grant_revision,
        )

    async def asyncTearDown(self) -> None:
        await self.browser.stop()
        await self.fixture.complete()

    async def start(self, permit: NodeEffectPermit | None = None) -> str:
        reply = await self.browser.operation_start(
            CallToolRequestParams(
                name="web_operation_start",
                arguments={
                    "tool": "local_browser_open",
                    "arguments": {"url": "https://example.com"},
                },
            ),
            permit or self.permit,
            self.identity,
        )
        return operation(reply).operation_id

    async def test_wrong_tool_identity_and_unrelated_calls_never_renew(self) -> None:
        handle = await self.start()
        self.fixture.grants.reset_mock()
        for identity, tool in (
            (self.identity, "local_browser_status"),
            (("foreign", *self.identity[1:]), "local_browser_open"),
        ):
            with self.assertRaises(ValueError):
                await self.browser.operation_control(
                    CallToolRequestParams(
                        name="web_operation_poll",
                        arguments={"operation_id": handle, "tool": tool},
                    ),
                    self.permit,
                    identity,
                )
        status = await self.browser.execute(
            CallToolRequestParams(name="local_browser_status", arguments={}), self.permit
        )
        assert status.result is not None
        pending = BrowserPreparingReceipt.model_validate(
            status.result.structured_content
        ).result.pending
        assert pending is not None
        self.assertEqual(pending.operation_id, handle)
        self.fixture.grants.assert_not_awaited()
        await self.browser.operation_control(
            CallToolRequestParams(
                name="web_operation_poll",
                arguments={"operation_id": handle, "tool": "local_browser_open"},
            ),
            self.permit,
            self.identity,
        )
        self.fixture.grants.assert_awaited_once()
        self.fixture.finish.set()
        await self.fixture.complete()
        completed = await self.browser.operation_control(
            CallToolRequestParams(
                name="web_operation_poll",
                arguments={"operation_id": handle, "tool": "local_browser_open"},
            ),
            self.permit,
            self.identity,
        )
        self.assertEqual(operation(completed).state, OperationState.COMPLETED)
        with self.assertRaises(ValueError):
            await self.start()
        self.assertEqual(self.fixture.exchange.await_count, 1)

    async def test_cancel_never_resumes_and_unknown_handles_never_replay(self) -> None:
        handle = await self.start()
        self.fixture.grants.reset_mock()
        cancelled = await self.browser.operation_control(
            CallToolRequestParams(
                name="web_operation_cancel",
                arguments={"operation_id": handle},
            ),
            self.permit,
            self.identity,
        )
        self.assertEqual(operation(cancelled).state, OperationState.CANCELLED)
        with self.assertRaises(ValueError):
            await self.browser.operation_control(
                CallToolRequestParams(
                    name="web_operation_poll",
                    arguments={"operation_id": "old", "tool": "local_browser_open"},
                ),
                self.permit,
                self.identity,
            )
        self.fixture.grants.assert_not_awaited()

    async def test_expired_and_unprepared_start_cannot_grant(self) -> None:
        self.browser.status_warm = False
        with self.assertRaises(ValueError):
            await self.start()
        self.browser.status_warm = True
        with self.assertRaises(ValueError):
            await self.start(self.permit.model_copy(update={"expires_at": 1}))
        self.fixture.grants.assert_not_awaited()
