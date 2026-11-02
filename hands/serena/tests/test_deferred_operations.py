"""Private handles never resume another identity/tool or replay an effect."""

import asyncio
import json
import time
import unittest
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from mcp.types import CallToolRequestParams, CallToolResult, TextContent
from serena_hand.supervisor import SerenaSupervisor

from hand_runtime.deferred_calls import DeferredCalls, OperationView
from hand_runtime.presentation.deferred_operations import (
    CancelOperationRequest,
    PollOperationRequest,
)
from hand_runtime.process_lease_domain import LeaseIdentity
from node_protocol.effect import NodeEffectPermit


@dataclass
class LeaseFixture:
    identity: LeaseIdentity | None
    grant: AsyncMock = field(default_factory=lambda: AsyncMock(return_value=True))


class DeferredOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.lock = asyncio.Lock()
        self.finish = asyncio.Event()
        now = int(time.time())
        self.permit = NodeEffectPermit(
            module="serena",
            node_uuid=uuid4(),
            placement_uuid=uuid4(),
            project_uuid=uuid4(),
            workspace_uuid=uuid4(),
            actor_uuid=uuid4(),
            agent_session_uuid=uuid4(),
            grant_revision=3,
            request_uuid=uuid4(),
            fingerprint="a" * 64,
            body_digest="b" * 64,
            bearer_digest="c" * 64,
            arguments_digest="d" * 64,
            method="tools/call",
            tool="serena_operation_start",
            resource_id="workspace:" + "a" * 80,
            issued_at=now,
            expires_at=now + 4,
        )
        self.identity: LeaseIdentity = (
            str(self.permit.actor_uuid),
            str(self.permit.agent_session_uuid),
            3,
        )
        self.lease = LeaseFixture(self.identity)
        self.stop = AsyncMock(side_effect=self.interrupt)
        self.recover = Mock()
        self.calls = DeferredCalls(
            "serena",
            lock=self.lock,
            lease=self.lease,
            ready=lambda: True,
            tools=lambda: {"rename_symbol"},
            execute=self.execute,
            stop=self.stop,
            recover=self.recover,
        )

    async def execute(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
    ) -> CallToolResult:
        self.assertEqual(call.name, "rename_symbol")
        self.assertEqual(call.arguments, {"new_name": "Owned"})
        self.assertIs(permit, self.permit)
        await self.finish.wait()
        return CallToolResult(
            content=[TextContent(type="text", text="native result")], is_error=False
        )

    async def interrupt(self) -> None:
        self.calls.interrupt()

    async def asyncTearDown(self) -> None:
        self.calls.interrupt()
        await asyncio.sleep(0)

    @staticmethod
    def view(result: CallToolResult) -> OperationView:
        return OperationView.model_validate_json(json.dumps(result.structured_content))

    async def start(self) -> str:
        result = await self.calls.start(
            CallToolRequestParams(
                name="serena_operation_start",
                arguments={
                    "tool": "rename_symbol",
                    "arguments": {"new_name": "Owned"},
                },
            ),
            self.permit,
            self.identity,
        )
        return self.view(result).operation_id

    async def poll(self, operation: str) -> OperationView:
        result = await self.calls.control(
            "serena_operation_poll",
            PollOperationRequest(operation_id=operation, tool="rename_symbol"),
            self.permit,
            self.identity,
        )
        return self.view(result)

    async def test_wrong_actor_session_revision_tool_and_unknown_handle_do_not_renew(self) -> None:
        operation = await self.start()
        self.lease.grant.reset_mock()
        identities: tuple[LeaseIdentity, ...] = (
            ("foreign", self.identity[1], 3),
            (self.identity[0], "other", 3),
            (self.identity[0], self.identity[1], 4),
        )
        for identity in identities:
            with self.assertRaises(ValueError):
                await self.calls.control(
                    "serena_operation_poll",
                    PollOperationRequest(operation_id=operation, tool="rename_symbol"),
                    self.permit,
                    identity,
                )
        for token, tool in ((operation, "initial_instructions"), ("old", "rename_symbol")):
            with self.assertRaises(ValueError):
                await self.calls.control(
                    "serena_operation_poll",
                    PollOperationRequest(operation_id=token, tool=tool),
                    self.permit,
                    self.identity,
                )
        self.lease.grant.assert_not_awaited()

    async def test_unrelated_native_request_cannot_resume_pending_mutation(self) -> None:
        await self.start()
        self.lease.grant.reset_mock()
        with patch("serena_hand.supervisor.ProcessLease", return_value=self.lease):
            supervisor = SerenaSupervisor(".")
        supervisor.lock = self.lock
        supervisor.deferred = self.calls
        with self.assertRaises(ValueError):
            await supervisor.call(
                CallToolRequestParams(name="initial_instructions", arguments={}),
                self.permit,
            )
        self.lease.grant.assert_not_awaited()
        self.stop.assert_not_awaited()

    async def test_owned_poll_finishes_one_effect_and_duplicate_start_is_rejected(self) -> None:
        operation = await self.start()
        self.lease.grant.reset_mock()
        await self.poll(operation)
        self.lease.grant.assert_awaited_once()
        self.finish.set()
        async with asyncio.timeout(1):
            while True:
                result = await self.poll(operation)
                if result.state != "running":
                    break
                await asyncio.sleep(0)
        self.assertEqual(result.state, "completed")
        self.assertIsNotNone(result.result)
        assert result.result is not None
        self.assertFalse(result.result.is_error)
        self.assertEqual(result.result.content, [TextContent(type="text", text="native result")])
        with self.assertRaises(ValueError):
            await self.start()

    async def test_cancel_stops_without_resume_or_rollback(self) -> None:
        operation = await self.start()
        self.lease.grant.reset_mock()
        result = await self.calls.control(
            "serena_operation_cancel",
            CancelOperationRequest(operation_id=operation),
            self.permit,
            self.identity,
        )
        self.assertEqual(self.view(result).state, "cancelled")
        self.lease.grant.assert_not_awaited()
        self.stop.assert_awaited_once()
        self.recover.assert_called_once()

    async def test_expired_unknown_recursive_and_concurrent_starts_cannot_dispatch(self) -> None:
        for tool in ("unknown", "serena_operation_start"):
            with self.assertRaises(ValueError):
                await self.calls.start(
                    CallToolRequestParams(
                        name="serena_operation_start",
                        arguments={
                            "tool": tool,
                            "arguments": {},
                        },
                    ),
                    self.permit,
                    self.identity,
                )
        self.permit = self.permit.model_copy(update={"expires_at": int(time.time()) - 1})
        with self.assertRaises(ValueError):
            await self.start()
        self.lease.grant.assert_not_awaited()
        self.permit = self.permit.model_copy(update={"expires_at": int(time.time()) + 4})
        await self.start()
        self.lease.grant.reset_mock()
        with self.assertRaises(ValueError):
            await self.start()
        self.lease.grant.assert_not_awaited()
