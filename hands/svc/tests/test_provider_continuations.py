"""Private continuation authority and configured duration, no provider effects."""

import asyncio
import json
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from mcp.types import CallToolRequestParams, CallToolResult

from hand_runtime.deferred_calls import OperationView
from hand_runtime.domain.deferred_operations import DeferredRecord, OperationState
from hand_runtime.presentation.deferred_operations import parse_operation_handle
from hand_runtime.process_lease import ProcessLease
from hand_runtime.process_lease_domain import (
    LeaseExpiryInput,
    LeaseIdentity,
    LeaseIdentityInput,
    ProcessAuthority,
)
from hand_runtime.provider_ipc import ProviderContext
from hand_runtime.provider_supervisor import ProviderSupervisor
from node_protocol.effect import NodeEffectPermit
from node_protocol.provider_context import GitRuntimePolicy, InvocationPolicies


class LeaseFixture(ProcessLease):
    def __init__(self, identity: LeaseIdentity) -> None:
        self.identity = identity
        self.grants: list[LeaseIdentity] = []

    async def grant(self, identity_tuple: LeaseIdentityInput, expires_at: LeaseExpiryInput) -> bool:
        authority = ProcessAuthority.parse(identity_tuple, expires_at)
        self.grants.append(authority.identity)
        preserved = self.identity == authority.identity
        self.identity = authority.identity
        return preserved


class ProviderFixture(ProviderSupervisor):
    def __init__(self, done: asyncio.Event, lease: LeaseFixture) -> None:
        with patch("hand_runtime.provider_supervisor.ProcessLease", return_value=lease):
            super().__init__("svc")
        self.done = done
        self.tools = {"github_clone"}
        self.stops = 0
        self.recoveries = 0
        self.exchanges = 0

    def ready(self) -> bool:
        return True

    def _schedule_warmup(self) -> None:
        self.recoveries += 1

    async def stop(self) -> None:
        self.stops += 1
        self.active_context = None
        self.deferred.interrupt()

    async def exchange(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
        context: ProviderContext,
        *,
        background: bool = False,
    ) -> CallToolResult:
        del permit, context
        assert call.name == "github_clone" and background
        self.exchanges += 1
        await self.done.wait()
        return CallToolResult(content=[], structured_content={"native": True}, is_error=False)


def operation_view(reply: CallToolResult) -> OperationView:
    assert reply.structured_content is not None
    return OperationView.model_validate_json(json.dumps(reply.structured_content))


class ProviderContinuations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.done = asyncio.Event()
        self.permit = NodeEffectPermit(
            module="svc",
            node_uuid=uuid4(),
            placement_uuid=uuid4(),
            project_uuid=uuid4(),
            workspace_uuid=uuid4(),
            actor_uuid=uuid4(),
            agent_session_uuid=uuid4(),
            request_uuid=uuid4(),
            grant_revision=2,
            fingerprint="a" * 64,
            body_digest="b" * 64,
            bearer_digest="c" * 64,
            arguments_digest="d" * 64,
            method="tools/call",
            tool="svc_operation_start",
            resource_id="fixture-" * 10,
            issued_at=int(time.time()),
            expires_at=int(time.time()) + 60,
        )
        self.context = ProviderContext(accounts=())
        self.lease = LeaseFixture(
            (str(self.permit.actor_uuid), str(self.permit.agent_session_uuid), 2)
        )
        self.supervisor = ProviderFixture(self.done, self.lease)

    async def asyncTearDown(self) -> None:
        self.supervisor.deferred.interrupt()
        await asyncio.sleep(0)

    async def start(self) -> str:
        result = await self.supervisor.execute(
            CallToolRequestParams(
                name="svc_operation_start",
                arguments={"tool": "github_clone", "arguments": {"account_id": "mine"}},
            ),
            self.permit,
            self.context,
        )
        await asyncio.sleep(0)
        return operation_view(result).operation_id

    async def poll(
        self, handle: str, account: str = "mine", context: ProviderContext | None = None
    ) -> OperationView:
        result = await self.supervisor.execute(
            CallToolRequestParams(
                name="svc_operation_poll",
                arguments={"operation_id": handle, "tool": "github_clone", "account_id": account},
            ),
            self.permit,
            context if context is not None else self.context,
        )
        return operation_view(result)

    def record(self, handle: str) -> DeferredRecord[CallToolResult]:
        record = self.supervisor.deferred.lookup(parse_operation_handle(handle))
        if record is None:
            raise AssertionError("Expected the retained operation")
        return record

    async def test_poll_other_account_never_renews(self) -> None:
        handle = await self.start()
        self.lease.grants.clear()
        with self.assertRaises(ValueError):
            await self.poll(handle, "foreign")
        self.assertEqual(self.lease.grants, [])
        self.assertEqual(self.supervisor.stops, 0)
        await self.poll(handle)
        self.assertEqual(len(self.lease.grants), 1)

    async def test_explicit_execution_timeout_stops_effect(self) -> None:
        with patch.dict(
            "os.environ", {"BRIAREUS_RUNTIME_POLICY": '{"execution_timeout_seconds":0.01}'}
        ):
            handle = await self.start()
            await asyncio.sleep(0.03)
            self.assertEqual(self.record(handle).state, OperationState.FAILED)
            self.assertEqual(self.supervisor.stops, 1)

    async def test_default_duration_none_and_unrelated_tool_denied(self) -> None:
        with patch.dict("os.environ", {"BRIAREUS_RUNTIME_POLICY": "{}"}):
            handle = await self.start()
            await asyncio.sleep(0.02)
            self.assertEqual(self.record(handle).state, OperationState.RUNNING)
            with self.assertRaises(ValueError):
                await self.supervisor.execute(
                    CallToolRequestParams(name="github_clone", arguments={}),
                    self.permit,
                    self.context,
                )
            self.done.set()
            await asyncio.sleep(0.01)
            self.assertEqual(self.record(handle).state, OperationState.COMPLETED)
            self.assertIsNone(self.supervisor.active_context)

    async def test_policy_change_stops_before_lease_renewal(self) -> None:
        handle = await self.start()
        self.lease.grants.clear()
        changed = ProviderContext(
            accounts=(),
            policies=InvocationPolicies(
                github_runtime=GitRuntimePolicy(
                    local_first_guidance=True,
                    local_git_transport_enabled=False,
                    remote_source_mutations_enabled=False,
                )
            ),
        )
        with self.assertRaisesRegex(ValueError, "policy changed"):
            await self.poll(handle, context=changed)
        self.assertEqual(self.lease.grants, [])
        self.assertEqual(self.supervisor.stops, 1)

    async def test_lost_start_reply_lookup_does_not_reexecute(self) -> None:
        handle = await self.start()
        result = await self.poll("request:" + str(self.permit.request_uuid))
        self.assertEqual(result.operation_id, handle)
        self.assertEqual(self.supervisor.exchanges, 1)
