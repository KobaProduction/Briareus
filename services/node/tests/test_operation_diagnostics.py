"""Safe authoritative failure facts, durable rollback and wire compatibility."""

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from journal_fixture import JournalFixture as Journal
from node_agent.application.placement import ApplyPlacement, OperationSnapshot
from node_agent.diagnostics import state_diagnostic
from node_agent.docker_engine import DockerEngine, EngineFailure
from node_agent.infrastructure.container_models import InspectedState
from node_agent.infrastructure.placement import ControllerPlacementRuntime, JournalOperationStore
from node_agent.planner import Instance
from test_native_replacement_repair import NativeDaemon
from test_reconciliation import fixture

from node_protocol import Deployment
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.grpc_codec import decode_operation, encode_operation
from node_protocol.reply_wire import OperationWire


class OperationDiagnosticTests(unittest.TestCase):
    def test_state_facts_never_copy_logs_or_infer_stack_cause(self) -> None:
        actual = state_diagnostic(
            "checking",
            InspectedState.model_validate(
                {
                    "Running": False,
                    "ExitCode": 3,
                    "OOMKilled": False,
                    "Error": "secret-provider-url",
                    "Health": {
                        "Status": "unhealthy",
                        "Log": [{"ExitCode": 1, "Output": "secret-token"}],
                    },
                }
            ),
        ).model_dump(mode="json", exclude_none=True)
        self.assertEqual(
            actual,
            {
                "stage": "checking",
                "component": "worker",
                "reason": "process_exited",
                "exit_code": 3,
                "oom_killed": False,
                "health_status": "unhealthy",
                "health_exit_code": 1,
            },
        )
        self.assertNotIn("secret", json.dumps(actual))
        self.assertEqual(
            state_diagnostic(
                "checking", InspectedState(running=False, exit_code=137, oom_killed=True)
            ).reason,
            "oom",
        )
        probe = state_diagnostic(
            "checking",
            InspectedState.model_validate(
                {
                    "Running": True,
                    "ExitCode": 0,
                    "Health": {"Status": "unhealthy", "Log": [{"ExitCode": -1}]},
                }
            ),
        ).model_dump(mode="json", exclude_none=True)
        self.assertNotIn("exit_code", probe)
        self.assertEqual(probe["health_exit_code"], -1)
        self.assertEqual(probe["reason"], "unhealthy")
        with self.assertRaises(ValueError):
            FailureDiagnostic.model_validate({**actual, "message": "secret"})
        self.assertIsNone(
            EngineFailure("Workspace helper cleanup is unresolved secret-token").reason
        )
        self.assertEqual(
            EngineFailure("Workspace helper cleanup is unresolved").reason,
            "workspace_cleanup_uncertain",
        )

    def test_protobuf_roundtrip_and_old_payload_omission(self) -> None:
        old = OperationWire(
            operation_uuid=uuid4(), sequence=1, phase="failed", error="UPDATE_FAILED"
        )
        self.assertEqual(decode_operation(encode_operation(old)), old)
        self.assertNotIn("diagnostic", old.model_dump(mode="json", exclude_none=True))
        current = OperationWire(
            operation_uuid=old.operation_uuid,
            sequence=old.sequence,
            phase=old.phase,
            error=old.error,
            diagnostic=FailureDiagnostic(
                stage="checking",
                component="worker",
                reason="oom",
                exit_code=137,
                oom_killed=True,
                health_status="unhealthy",
                health_exit_code=-1,
            ),
        )
        self.assertEqual(decode_operation(encode_operation(current)), current)


@dataclass
class EarlyFailureExecution:
    engine: DockerEngine

    async def observed(self) -> list[Instance]:
        raise AssertionError("Rootless refusal must precede inventory")

    async def wait_ready(self, container: str) -> None:
        del container
        raise AssertionError("Rootless refusal must precede readiness")

    async def failure_diagnostic(
        self,
        receipt: OperationSnapshot,
        desired: Deployment,
        *,
        deadline_expired: bool = False,
    ) -> FailureDiagnostic:
        del receipt, desired, deadline_expired
        raise AssertionError("Exact engine failure must preserve its original diagnostic")


class ControllerDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_internal_failure_is_durable_before_rollback(self) -> None:
        node, spec = fixture()

        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "journal-fixture")
            try:
                operation = uuid4()
                daemon = NativeDaemon(spec)
                async with daemon.engine() as engine:
                    engine.workspace_cleanup_uncertain = True
                    await ApplyPlacement(
                        lambda: node,
                        JournalOperationStore(journal),
                        ControllerPlacementRuntime(EarlyFailureExecution(engine)),
                    ).execute(operation, 1, spec)
                self.assertEqual(daemon.seen, [])
                result = await journal.get(operation)
                assert result is not None
                self.assertEqual(result.error, "UPDATE_FAILED")
                assert result.diagnostic is not None
                self.assertEqual(
                    result.diagnostic.model_dump(mode="json", exclude_none=True),
                    {
                        "stage": "queued",
                        "component": "engine",
                        "reason": "workspace_cleanup_uncertain",
                    },
                )
            finally:
                (await journal.close())
