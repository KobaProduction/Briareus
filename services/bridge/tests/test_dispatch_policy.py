from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from mcp.types import CallToolRequestParams
from pydantic import JsonValue

from bridge.domain.project_dispatch import (
    ExpectedOwnerSchema,
    ProjectGatewayDispatchUnavailable,
    VerifiedOwnerReadiness,
    require_matching_owner_schema,
)
from bridge.infrastructure.project_codec import require_command_input


class OwnerReadinessPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime.now(UTC)
        service_uuid = uuid4()
        self.expected = ExpectedOwnerSchema(
            "access",
            "briareus_access",
            "0001",
            "authorization_owner",
            service_uuid,
        )
        self.snapshot = VerifiedOwnerReadiness(
            "access",
            "briareus_access",
            "0001",
            "authorization_owner",
            service_uuid,
            self.now + timedelta(seconds=30),
        )

    def test_accepts_exact_current_release(self) -> None:
        require_matching_owner_schema("access", self.snapshot, self.expected, now=self.now)

    def test_rejects_mismatched_authority_and_release(self) -> None:
        snapshots = (
            replace(self.snapshot, owner="identity"),
            replace(self.snapshot, database="briareus_identity"),
            replace(self.snapshot, database_role="another_owner"),
            replace(self.snapshot, schema_head="another_release"),
            replace(self.snapshot, owner_service_id=uuid4()),
            replace(self.snapshot, expires_at=self.now),
            replace(self.snapshot, expires_at=self.now.replace(tzinfo=None)),
        )
        for snapshot in snapshots:
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(ProjectGatewayDispatchUnavailable) as caught:
                    require_matching_owner_schema("access", snapshot, self.expected, now=self.now)
                self.assertEqual(caught.exception.code, "PROJECT_OWNER_SCHEMA_REVISION_INVALID")

    def test_owner_self_report_cannot_replace_trusted_manifest(self) -> None:
        expected = replace(self.expected, expected_head="next_release")
        with self.assertRaises(ProjectGatewayDispatchUnavailable):
            require_matching_owner_schema("access", self.snapshot, expected, now=self.now)


class DispatchArgumentPolicyTests(unittest.TestCase):
    def test_nested_credentials_are_rejected_case_insensitively(self) -> None:
        request = CallToolRequestParams(
            name="write_status", arguments={"payload": [{"AcCeSs_ToKeN": "private"}]}
        )
        with self.assertRaises(ProjectGatewayDispatchUnavailable) as caught:
            require_command_input(request)
        self.assertEqual(caught.exception.code, "PROJECT_ARGUMENTS_FORBIDDEN")

    def test_total_budget_is_shared_across_branches(self) -> None:
        request = CallToolRequestParams(
            name="write_status", arguments={"payload": [[None] * 1024, [None] * 1024]}
        )
        with self.assertRaises(ProjectGatewayDispatchUnavailable) as caught:
            require_command_input(request)
        self.assertEqual(caught.exception.code, "PROJECT_ARGUMENTS_TOO_LARGE")

    def test_depth_budget_is_preserved(self) -> None:
        value: JsonValue = None
        for _ in range(13):
            value = [value]
        request = CallToolRequestParams(name="write_status", arguments={"payload": value})
        with self.assertRaises(ProjectGatewayDispatchUnavailable) as caught:
            require_command_input(request)
        self.assertEqual(caught.exception.code, "PROJECT_ARGUMENTS_TOO_DEEP")


if __name__ == "__main__":
    unittest.main()
