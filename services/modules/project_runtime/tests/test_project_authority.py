"""Current authority is revalidated before private Project resource use."""

import hashlib
import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel

from modules.project_runtime.authorization import (
    ProjectAccessDenied,
    ProjectAction,
    ProjectInvocation,
    ProjectOwnerFence,
    ProjectPermit,
    ProjectRuntimeAuthority,
    canonical_request_fingerprint,
)
from modules.project_runtime.domain.effect_identity import (
    EmbeddedEffectIdentity,
    OriginalEffectIdentity,
)
from modules.project_runtime.domain.effect_receipt import OwnerEffectUnavailable


class FilePathRequest(BaseModel):
    path: str


def permit(invocation: ProjectInvocation) -> ProjectPermit:
    fence = ProjectOwnerFence(1, 0, uuid4(), 2, "a" * 64, 0, uuid4(), 3, 0, uuid4())
    return ProjectPermit(
        invocation.project_id,
        uuid4(),
        invocation.session_uuid,
        "resources.use",
        datetime.now(UTC) + timedelta(seconds=5),
        3,
        "a" * 64,
        "project",
        invocation.project_id,
        fence,
    )


class AccessPort:
    def __init__(self, current: ProjectPermit) -> None:
        self.current = current

    async def authorize(
        self, invocation: ProjectInvocation, action: ProjectAction
    ) -> ProjectPermit:
        if action != "resources.use":
            raise AssertionError("fixture called without the expected authority request")
        return self.current


class CurrentAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_current_owner_fences_are_required(self) -> None:
        invocation = ProjectInvocation(uuid4(), uuid4())
        current = permit(invocation)
        port = AccessPort(current)
        authority = ProjectRuntimeAuthority(port)
        self.assertEqual(await authority.require(invocation, "resources.use"), current)
        for invalid in (
            replace(current, project_id=uuid4()),
            replace(current, session_uuid=uuid4()),
            replace(current, action="files.read"),
            replace(current, owner_fence=None),
            replace(current, decision_version=2),
            replace(current, project_access_revision="b" * 64),
            replace(current, project_owner_id=uuid4()),
            replace(current, project_owner_scope=None),
            replace(current, expires_at=datetime.now(UTC) - timedelta(seconds=1)),
            replace(current, expires_at=datetime(2020, 1, 1, tzinfo=UTC).replace(tzinfo=None)),
        ):
            port.current = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ProjectAccessDenied) as raised:
                await authority.require(invocation, "resources.use")
            self.assertEqual(raised.exception.code, "PROJECT_AUTHORIZATION_INVALID")


class OriginalOperationTests(unittest.TestCase):
    def test_original_operation_and_embedded_idempotency_cannot_change(self) -> None:
        operation_uuid = uuid4()
        identity = OriginalEffectIdentity.bind(operation_uuid, operation_uuid)
        identity.require_payload(EmbeddedEffectIdentity((operation_uuid,), str(operation_uuid)))
        with self.assertRaises(OwnerEffectUnavailable) as raised:
            OriginalEffectIdentity.bind(operation_uuid, uuid4())
        self.assertEqual(raised.exception.code, "OWNER_ORIGINAL_UUID_MISMATCH")
        with self.assertRaises(OwnerEffectUnavailable) as raised:
            identity.require_payload(EmbeddedEffectIdentity((uuid4(),), str(operation_uuid)))
        self.assertEqual(raised.exception.code, "OWNER_EMBEDDED_ORIGINAL_UUID_MISMATCH")
        with self.assertRaises(OwnerEffectUnavailable) as raised:
            identity.require_payload(EmbeddedEffectIdentity((), str(uuid4())))
        self.assertEqual(raised.exception.code, "OWNER_EMBEDDED_IDEMPOTENCY_KEY_MISMATCH")

    def test_fingerprint_keeps_exact_normalized_wire_preimage(self) -> None:
        project_uuid, session_uuid, request_uuid = uuid4(), uuid4(), uuid4()
        actual = canonical_request_fingerprint(
            project_id=project_uuid,
            session_uuid=session_uuid,
            action="files.read",
            request_uuid=request_uuid,
            backend="files",
            tool="file_read",
            arguments=FilePathRequest(path="x"),
        )
        expected = json.dumps(
            [
                "private-project-op-v1",
                str(project_uuid),
                str(session_uuid),
                str(request_uuid),
                "files.read",
                "files",
                "file_read",
                {"path": "x"},
            ],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(actual, hashlib.sha256(expected).hexdigest())
