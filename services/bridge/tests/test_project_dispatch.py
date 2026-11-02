from __future__ import annotations

import hashlib
import json
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from mcp.types import CallToolRequestParams

from bridge.application.project_contracts import (
    FileUnverified,
    FileUpload,
    FileWriteStatus,
    ProjectCommand,
    ProjectResult,
)
from bridge.application.project_dispatch import AuthorizedToolForward, ProjectGatewayDispatch
from bridge.domain.project_dispatch import (
    ExpectedOwnerSchema,
    OwnerServiceName,
    ProjectGatewayDispatchUnavailable,
    VerifiedOwnerReadiness,
)
from bridge.infrastructure.project_codec import command_fingerprint, normalize_command
from modules.project_runtime import (
    ProjectAction,
    ProjectInvocation,
    ProjectPermit,
)

_DATABASES: dict[OwnerServiceName, str] = {
    "identity": "briareus_identity",
    "access": "briareus_access",
    "control": "briareus_platform",
    "catalog": "briareus_resources",
}


class ReadinessStub:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.service_uuid = uuid4()
        self.expired = False

    async def expected_schema(self, owner: OwnerServiceName) -> ExpectedOwnerSchema:
        self.trace.append(f"manifest:{owner}")
        return ExpectedOwnerSchema(owner, _DATABASES[owner], "release", "owner", self.service_uuid)

    async def require_current_owner_schema(
        self,
        invocation: ProjectInvocation,
        *,
        owner: OwnerServiceName,
    ) -> VerifiedOwnerReadiness:
        self.trace.append(f"snapshot:{owner}:{invocation.project_id}")
        deadline = datetime.now(UTC) + timedelta(seconds=-1 if self.expired else 30)
        return VerifiedOwnerReadiness(
            owner,
            _DATABASES[owner],
            "release",
            "owner",
            self.service_uuid,
            deadline,
        )


class AuthorityStub:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    async def require(self, invocation: ProjectInvocation, action: ProjectAction) -> ProjectPermit:
        self.trace.append("authority")
        return ProjectPermit(
            invocation.project_id,
            uuid4(),
            invocation.session_uuid,
            action,
            datetime.now(UTC) + timedelta(seconds=30),
            1,
        )


class ForwarderStub:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.timeout = False
        self.requests: list[AuthorizedToolForward] = []

    async def classify(self, backend: str, tool: str) -> ProjectAction | None:
        self.trace.append(f"classify:{backend}:{tool}")
        return "files.write"

    def fingerprint(
        self,
        invocation: ProjectInvocation,
        action: ProjectAction,
        request_uuid: UUID,
        backend: str,
        tool: str,
        command: ProjectCommand,
    ) -> str:
        return command_fingerprint(invocation, action, request_uuid, backend, tool, command)

    async def forward(self, request: AuthorizedToolForward) -> ProjectResult:
        self.trace.append("forward")
        self.requests.append(request)
        if self.timeout:
            raise TimeoutError("private backend diagnostic")
        return FileUnverified(request.request_uuid)


class ProjectDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.trace: list[str] = []
        self.readiness = ReadinessStub(self.trace)
        self.forwarder = ForwarderStub(self.trace)
        self.invocation = ProjectInvocation(uuid4(), uuid4())
        self.dispatch = ProjectGatewayDispatch(
            AuthorityStub(self.trace),
            classifier=self.forwarder,
            forwarder=self.forwarder,
            readiness=self.readiness,
            release_manifest=self.readiness,
        )

    async def test_stale_owner_stops_before_classification_and_authorization(self) -> None:
        self.readiness.expired = True
        with self.assertRaises(ProjectGatewayDispatchUnavailable) as caught:
            await self.dispatch.dispatch(
                self.invocation,
                backend="files",
                tool="write_status",
                arguments=FileWriteStatus(operation_uuid=uuid4(), destination="file"),
                request_uuid=uuid4(),
            )
        self.assertEqual(caught.exception.code, "PROJECT_OWNER_SCHEMA_UNAVAILABLE")
        self.assertFalse(any(item.startswith("classify:") for item in self.trace))
        self.assertNotIn("authority", self.trace)
        self.assertEqual(self.forwarder.requests, [])

    async def test_uncertain_write_retains_uuid_and_is_forwarded_once(self) -> None:
        operation_uuid = uuid4()
        self.forwarder.timeout = True
        with self.assertRaises(ProjectGatewayDispatchUnavailable) as caught:
            await self.dispatch.dispatch(
                self.invocation,
                backend="files",
                tool="upload_base64",
                arguments=FileUpload(
                    destination="file",
                    operation_uuid=operation_uuid,
                    size_bytes=0,
                    sha256=hashlib.sha256(b"").hexdigest(),
                    content_base64="",
                ),
                request_uuid=operation_uuid,
            )
        self.assertEqual(caught.exception.code, "PROJECT_FILE_OUTCOME_UNKNOWN")
        self.assertEqual(caught.exception.operation_uuid, operation_uuid)
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual(len(self.forwarder.requests), 1)
        self.assertEqual(self.forwarder.requests[0].request_uuid, operation_uuid)
        self.assertEqual(self.trace[-2:], ["authority", "forward"])

    async def test_payload_operation_mismatch_stops_before_effect(self) -> None:
        with self.assertRaises(ProjectGatewayDispatchUnavailable) as caught:
            await self.dispatch.dispatch(
                self.invocation,
                backend="files",
                tool="write_status",
                arguments=FileWriteStatus(operation_uuid=uuid4(), destination="file"),
                request_uuid=uuid4(),
            )
        self.assertEqual(caught.exception.code, "PROJECT_REQUEST_UUID_MISMATCH")
        self.assertNotIn("authority", self.trace)
        self.assertEqual(self.forwarder.requests, [])

    async def test_typed_codec_preserves_original_canonical_fingerprint(self) -> None:
        operation_uuid = uuid4()
        command = normalize_command(
            "files",
            CallToolRequestParams(
                name="write_status",
                arguments={"operation_uuid": str(operation_uuid), "destination": "file"},
            ),
        )
        self.assertEqual(command, FileWriteStatus(operation_uuid, "file"))
        preimage = json.dumps(
            [
                "private-project-op-v1",
                str(self.invocation.project_id),
                str(self.invocation.session_uuid),
                str(operation_uuid),
                "files.write",
                "files",
                "write_status",
                {"operation_uuid": str(operation_uuid), "destination": "file"},
            ],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
        self.assertEqual(
            command_fingerprint(
                self.invocation, "files.write", operation_uuid, "files", "write_status", command
            ),
            hashlib.sha256(preimage).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
