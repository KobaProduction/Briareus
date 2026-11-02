"""Owned operations, bounded metadata recovery, and cancellation without effect replay."""

import asyncio
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from mcp.types import CallToolRequestParams, CallToolResult
from reverse_hand.isolated_supervisor import IsolatedSupervisor, operation_authority

from hand_runtime.errors import NodePreparing
from hand_runtime.presentation.deferred_operations import CancelOperationRequest
from node_protocol.effect import HumanEffectPermit, NodeEffectPermit


def permit() -> NodeEffectPermit:
    now = int(time.time())
    return NodeEffectPermit(
        module="reverse",
        node_uuid=uuid4(),
        placement_uuid=uuid4(),
        project_uuid=uuid4(),
        workspace_uuid=uuid4(),
        actor_uuid=uuid4(),
        agent_session_uuid=uuid4(),
        request_uuid=uuid4(),
        grant_revision=1,
        fingerprint="a" * 64,
        body_digest="b" * 64,
        bearer_digest="c" * 64,
        arguments_digest="d" * 64,
        method="tools/call",
        tool="analysis_start",
        resource_id="workspace:" + "a" * 80,
        issued_at=now,
        expires_at=now + 5,
    )


def child_fixture() -> MagicMock:
    child = MagicMock(spec=asyncio.subprocess.Process)
    child.returncode = None
    child.wait = AsyncMock()
    child.stdout = MagicMock()
    child.stdout.readline = AsyncMock(return_value=b'{"ready":true,"tools":[]}')
    return child


def operation_id(result: CallToolResult) -> str:
    assert result.structured_content is not None
    value = result.structured_content["operation_id"]
    assert isinstance(value, str)
    return value


class OperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.lease = MagicMock()
        self.lease.identity = None
        self.lease.grant = AsyncMock(return_value=True)
        self.lease.kill = AsyncMock()
        with patch("reverse_hand.isolated_supervisor.ProcessLease", return_value=self.lease):
            self.supervisor = IsolatedSupervisor("unused")
        self.supervisor.child = child_fixture()
        self.supervisor.prepared = True
        self.permit = permit()

    async def asyncTearDown(self) -> None:
        await self.supervisor.close()

    async def test_identity_handoff_prepares_before_any_engine_effect(self) -> None:
        self.lease.identity = (str(uuid4()), str(uuid4()), 1)
        self.lease.grant.return_value = False
        with patch.object(self.supervisor, "exchange", new_callable=AsyncMock) as exchange:
            with patch.object(self.supervisor, "schedule_recovery") as recover:
                with self.assertRaises(NodePreparing):
                    await self.supervisor.call(
                        CallToolRequestParams(
                            name="analysis_start",
                            arguments={
                                "engine": "radare2",
                                "tool": "radare2_list_binaries",
                                "arguments": {},
                            },
                        ),
                        self.permit,
                    )
                recover.assert_called_once()
            exchange.assert_not_awaited()
        self.assertEqual(self.supervisor.operations, {})

    async def test_warmup_forwards_transfer_setting_to_child(self) -> None:
        self.supervisor.prepared = False
        with (
            patch.dict("os.environ", {"BRIAREUS_PROJECT_TRANSFER": "1"}),
            patch(
                "reverse_hand.infrastructure.supervisor_io.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=child_fixture(),
            ) as spawn,
        ):
            await self.supervisor.warmup()
            self.assertEqual(spawn.call_args.kwargs["env"]["BRIAREUS_PROJECT_TRANSFER"], "1")
            self.assertTrue(self.supervisor.ready())

    async def test_background_result_requires_owner_and_unknown_ids_never_resume(self) -> None:
        finish = asyncio.Event()

        async def execute(
            call: CallToolRequestParams, evidence: NodeEffectPermit, *, long: bool = False
        ) -> CallToolResult:
            self.assertEqual(call.name, "analysis_start")
            self.assertIs(evidence, self.permit)
            self.assertTrue(long)
            await finish.wait()
            return CallToolResult(content=[], is_error=False)

        with patch.object(
            self.supervisor, "exchange", new_callable=AsyncMock, side_effect=execute
        ) as exchange:
            started = await self.supervisor.call(
                CallToolRequestParams(
                    name="analysis_start",
                    arguments={
                        "engine": "ghidra",
                        "tool": "import_file",
                        "arguments": {},
                    },
                ),
                self.permit,
            )
            operation = operation_id(started)
            await asyncio.sleep(0)
            self.assertEqual(exchange.await_count, 1)
            self.lease.identity = (
                str(self.permit.actor_uuid),
                str(self.permit.agent_session_uuid),
                1,
            )
            grants = self.lease.grant.await_count
            invalid = (
                self.permit.model_copy(update={"actor_uuid": uuid4()}),
                self.permit.model_copy(update={"agent_session_uuid": uuid4()}),
                self.permit.model_copy(update={"grant_revision": 2}),
                self.permit.model_copy(update={"expires_at": int(time.time()) - 1}),
            )
            for evidence in invalid:
                with self.assertRaises(ValueError):
                    await self.supervisor.call(
                        CallToolRequestParams(
                            name="analysis_poll", arguments={"operation_id": operation}
                        ),
                        evidence,
                    )
            with self.assertRaises(ValueError):
                await self.supervisor.call(
                    CallToolRequestParams(
                        name="analysis_poll", arguments={"operation_id": str(uuid4())}
                    ),
                    self.permit,
                )
            self.assertEqual(self.lease.grant.await_count, grants)
            polled = await self.supervisor.call(
                CallToolRequestParams(name="analysis_poll", arguments={"operation_id": operation}),
                self.permit,
            )
            assert polled.structured_content is not None
            self.assertEqual(polled.structured_content["state"], "running")
            finish.set()
            task = self.supervisor.operations[
                CancelOperationRequest(operation_id=operation).handle()
            ].task
            assert task is not None
            await task
            result = await self.supervisor.call(
                CallToolRequestParams(name="analysis_poll", arguments={"operation_id": operation}),
                self.permit,
            )
            assert result.structured_content is not None
            self.assertEqual(result.structured_content["state"], "completed")
            self.assertEqual(exchange.await_count, 1)

    async def test_cancel_kills_without_resuming_or_replaying(self) -> None:
        async def pending(
            call: CallToolRequestParams, evidence: NodeEffectPermit, *, long: bool = False
        ) -> CallToolResult:
            self.assertEqual(call.name, "analysis_start")
            self.assertIs(evidence, self.permit)
            self.assertTrue(long)
            await asyncio.Event().wait()
            raise AssertionError("Cancelled native effect must not finish")

        with (
            patch.object(
                self.supervisor, "exchange", new_callable=AsyncMock, side_effect=pending
            ) as exchange,
            patch.object(self.supervisor, "schedule_recovery") as recover,
        ):
            result = await self.supervisor.call(
                CallToolRequestParams(
                    name="analysis_start",
                    arguments={
                        "engine": "ghidra",
                        "tool": "import_file",
                        "arguments": {},
                    },
                ),
                self.permit,
            )
            token = operation_id(result)
            await asyncio.sleep(0)
            grants = self.lease.grant.await_count
            cancelled = await self.supervisor.call(
                CallToolRequestParams(name="analysis_cancel", arguments={"operation_id": token}),
                self.permit,
            )
            assert cancelled.structured_content is not None
            self.assertEqual(cancelled.structured_content["state"], "cancelled")
            self.assertEqual(self.lease.grant.await_count, grants)
            self.lease.kill.assert_awaited_once()
            recover.assert_called_once()
            self.assertEqual(exchange.await_count, 1)

    async def test_human_operation_requires_actor_project_and_current_resource_revision(
        self,
    ) -> None:
        evidence = HumanEffectPermit.model_validate(
            {
                **self.permit.model_dump(exclude={"agent_session_uuid", "grant_revision"}),
                "human": True,
                "resource_revision": 3,
            }
        )
        finish = asyncio.Event()

        async def execute(
            call: CallToolRequestParams, selected: HumanEffectPermit, *, long: bool = False
        ) -> CallToolResult:
            self.assertEqual(call.name, "analysis_start")
            self.assertIs(selected, evidence)
            self.assertTrue(long)
            await finish.wait()
            return CallToolResult(content=[], is_error=False)

        with patch.object(
            self.supervisor, "exchange", new_callable=AsyncMock, side_effect=execute
        ) as exchange:
            result = await self.supervisor.call(
                CallToolRequestParams(
                    name="analysis_start",
                    arguments={
                        "engine": "radare2",
                        "tool": "radare2_list_binaries",
                        "arguments": {},
                    },
                ),
                evidence,
            )
            token = operation_id(result)
            await asyncio.sleep(0)
            self.lease.identity = operation_authority(evidence).identity
            grants = self.lease.grant.await_count
            for field, value in (
                ("actor_uuid", uuid4()),
                ("project_uuid", uuid4()),
                ("resource_revision", 4),
                ("expires_at", int(time.time()) - 1),
            ):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    await self.supervisor.call(
                        CallToolRequestParams(
                            name="analysis_poll",
                            arguments={"operation_id": token},
                        ),
                        evidence.model_copy(update={field: value}),
                    )
            self.assertEqual(self.lease.grant.await_count, grants)
            finish.set()
            task = self.supervisor.operations[
                CancelOperationRequest(operation_id=token).handle()
            ].task
            assert task is not None
            await task
            polled = await self.supervisor.call(
                CallToolRequestParams(
                    name="analysis_poll",
                    arguments={"operation_id": token},
                ),
                evidence,
            )
            assert polled.structured_content is not None
            self.assertEqual(polled.structured_content["state"], "completed")
            self.assertEqual(exchange.await_count, 1)

    async def test_recovery_retries_metadata_only_at_bound(self) -> None:
        with patch.object(
            self.supervisor,
            "warmup",
            new_callable=AsyncMock,
            side_effect=ValueError("private diagnostic"),
        ) as warmup:
            with patch("reverse_hand.isolated_supervisor.RECOVERY_DELAYS", (0, 0, 0)):
                self.supervisor.schedule_recovery()
                first = self.supervisor.warming
                self.supervisor.schedule_recovery()
                self.assertIs(first, self.supervisor.warming)
                assert first is not None
                await first
            self.assertEqual(warmup.await_count, 3)


class UnifiedBuildInputsTests(unittest.TestCase):
    def test_radare_adapter_uses_declared_current_worktree_input(self) -> None:
        from node_protocol.catalog import ARTIFACTS

        root = Path(__file__).resolve().parents[3]
        dockerfile = (root / "hands/reverse/Dockerfile.node").read_text()
        self.assertIn("COPY hands/radare2/src/radare2_hand/ /app/src/radare2_hand/", dockerfile)
        self.assertNotIn("COPY --from=radare2-engine /app/src/radare2_hand", dockerfile)
        self.assertIn("hands/radare2/src/radare2_hand/**", ARTIFACTS["reverse"].inputs.paths)
        ignore = (root / "hands/reverse/Dockerfile.node.dockerignore").read_text()
        self.assertIn("!hands/radare2/src/radare2_hand/**", ignore)
