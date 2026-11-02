"""Human job ownership is proven by the supervisor, never child metadata."""

import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from mcp.types import CallToolRequestParams, CallToolResult
from terminal_hand.domain.human_principal import HumanOperationPrincipal
from terminal_hand.infrastructure.human_job_execution import HumanJobExecution
from terminal_hand.infrastructure.human_job_owners import HumanJobOwners
from terminal_hand.infrastructure.worker_codec import decode_command
from terminal_hand.infrastructure.worker_messages import TerminalReply


class HumanJobAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.owners = HumanJobOwners(self.root)
        self.principal = HumanOperationPrincipal(uuid4(), uuid4(), uuid4())
        self.fingerprint = "a" * 64

    def test_creation_is_durable_and_same_operation_cannot_change_owner_or_body(self) -> None:
        job = self.owners.bind(self.principal, self.fingerprint)
        self.assertEqual(job, self.principal.operation_uuid.hex)
        restored = HumanJobOwners(self.root)
        self.assertEqual(restored.bind(self.principal, self.fingerprint), job)
        restored.require(self.principal, job)
        foreign = HumanOperationPrincipal(
            uuid4(), self.principal.project_uuid, self.principal.operation_uuid
        )
        with self.assertRaises(ValueError):
            restored.bind(foreign, self.fingerprint)
        with self.assertRaises(ValueError):
            restored.bind(self.principal, "b" * 64)

    def test_same_project_different_user_and_same_user_different_project_are_denied(self) -> None:
        job = self.owners.bind(self.principal, self.fingerprint)
        alternatives = (
            HumanOperationPrincipal(uuid4(), self.principal.project_uuid, uuid4()),
            HumanOperationPrincipal(self.principal.actor_uuid, uuid4(), uuid4()),
        )
        for foreign in alternatives:
            with self.subTest(namespace=foreign.namespace):
                self.assertNotEqual(foreign.namespace, self.principal.namespace)
                self.assertEqual(self.owners.allowed(foreign), ())
                with self.assertRaises(ValueError):
                    self.owners.require(foreign, job)
        with self.assertRaises(ValueError):
            self.owners.require(self.principal, "../" + job)

    def test_exact_creation_identity_and_substituted_result(self) -> None:
        plan = HumanJobExecution(
            self.owners,
            self.principal,
            CallToolRequestParams(name="job_start", arguments={}),
            self.fingerprint,
        )
        command = decode_command(plan.request() + b"\n")
        self.assertIsNotNone(command.human)
        assert command.human is not None
        self.assertEqual(command.human.creation_id, self.principal.operation_uuid.hex)
        self.assertEqual(command.human.namespace, self.principal.namespace)
        self.assertIsNone(command.human.allowed_jobs)
        reply = TerminalReply(
            id=self.principal.operation_uuid,
            result=CallToolResult(
                content=[],
                structured_content={
                    "job_id": self.principal.operation_uuid.hex,
                },
            ),
        )
        plan.validate(reply)
        with self.assertRaises(ValueError):
            plan.validate(
                TerminalReply(
                    id=self.principal.operation_uuid,
                    result=CallToolResult(
                        content=[],
                        structured_content={
                            "job_id": uuid4().hex,
                        },
                    ),
                )
            )

    def test_unowned_point_request_is_rejected_before_dispatch(self) -> None:
        for tool in (
            "job_status",
            "job_read",
            "job_wait",
            "job_cancel",
            "job_write",
            "job_resize",
            "job_delete",
        ):
            with self.subTest(tool=tool), self.assertRaises(ValueError):
                HumanJobExecution(
                    self.owners,
                    self.principal,
                    CallToolRequestParams(name=tool, arguments={"job_id": uuid4().hex}),
                    self.fingerprint,
                ).request()

    def test_bulk_request_carries_only_verified_ids_and_rejects_forged_child_results(self) -> None:
        job = self.owners.bind(self.principal, self.fingerprint)
        for tool, payload in (
            ("job_list", {"jobs": [{"job_id": uuid4().hex}]}),
            ("job_cleanup", {"job_ids": [uuid4().hex]}),
        ):
            with self.subTest(tool=tool):
                plan = HumanJobExecution(
                    self.owners,
                    self.principal,
                    CallToolRequestParams(name=tool, arguments={}),
                    self.fingerprint,
                )
                command = decode_command(plan.request() + b"\n")
                assert command.human is not None
                self.assertEqual(command.human.allowed_jobs, (job,))
                with self.assertRaises(ValueError):
                    plan.validate(
                        TerminalReply(
                            id=self.principal.operation_uuid,
                            result=CallToolResult(content=[], structured_content=payload),
                        )
                    )
