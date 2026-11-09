from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from briareus_account_contracts import ResolvedAccount
from briareus_coolify.client import CoolifyClient, CoolifyClientError
from briareus_coolify.deployment_logs import deployment_log_page
from briareus_hand_runtime.tool_observability import invocation_result_payload
from briareus_http_transport.http_transport import HttpTransportResponse
from briareus_json_values import JsonObject, JsonValue


def client() -> CoolifyClient:
    return CoolifyClient(ResolvedAccount(
        id="source-id", alias="test", provider="coolify", auth_type="coolify_api_token",
        base_url="https://coolify.example.test", credential="configured-api-credential",
        created_at="created", updated_at="revision-1",
    ))


def response(raw: JsonObject, status: int = 200) -> HttpTransportResponse:
    return HttpTransportResponse(
        status=status, headers={}, body=json.dumps(raw).encode(), will_close=False
    )


def page(raw: JsonValue, *, offset: int | None = None, max_chars: int = 20_000) -> JsonObject:
    return deployment_log_page(
        {"logs": raw}, credential="configured-api-credential", offset=offset, max_chars=max_chars
    )


class CoolifyDeploymentLogsTests(unittest.TestCase):
    def test_api_reads_journal_with_existing_credentials_and_projects_only_log_output(self) -> None:
        provider = client()
        raw: JsonObject = {
            "deployment_uuid": "deployment-id", "status": "failed", "commit": "e3b80ee",
            "logs": json.dumps([
                {"timestamp": "2026-11-09T06:15:00Z", "type": "stderr",
                 "output": "Build failed: module not found", "hidden": True,
                 "command": "do-not-return-command", "unknown": "do-not-return-extra"},
            ]),
            "configuration_snapshot": {"secret": "do-not-return-configuration"},
        }
        with patch.object(provider._transport, "request", return_value=response(raw)) as request:
            result = provider.deployment_logs("deployment/id")
        self.assertEqual(result["status"], "failed")
        self.assertIn("2026-11-09T06:15:00Z stderr Build failed", str(result["logs"]))
        self.assertNotIn("do-not-return", json.dumps(result))
        self.assertEqual(request.call_args.args, ("GET", "/api/v1/deployments/deployment%2Fid"))
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"],
                         "Bearer configured-api-credential")

    def test_existing_metadata_tool_keeps_its_projection(self) -> None:
        provider = client()
        raw: JsonObject = {"status": "failed", "logs": "private journal"}
        with patch.object(provider._transport, "request", return_value=response(raw)):
            self.assertEqual(provider.deployment("id"), {"status": "failed"})

    def test_missing_null_and_empty_logs_are_distinct(self) -> None:
        missing = deployment_log_page({}, credential="", offset=None, max_chars=100)
        self.assertEqual(missing["reason"], "not_returned")
        self.assertFalse(missing["logs_available"])
        self.assertIn("read:sensitive", str(missing["hint"]))
        self.assertEqual(page(None)["reason"], "null")
        for raw in ("", "[]", []):
            with self.subTest(raw=raw):
                result = page(raw)
                self.assertTrue(result["logs_available"])
                self.assertEqual(result["logs"], "")

    def test_upstream_permission_denial_is_not_replaced_with_an_empty_journal(self) -> None:
        provider = client()
        with (
            patch.object(provider._transport, "request", return_value=response({}, 403)),
            self.assertRaisesRegex(CoolifyClientError, "Coolify HTTP 403"),
        ):
            provider.deployment_logs("id")

    def test_tail_and_forward_pages_preserve_unicode_and_report_bounds(self) -> None:
        text = "first\n\u043e\u0448\u0438\u0431\u043a\u0430 🚀\nlast"
        tail = page(text, max_chars=4)
        self.assertEqual(tail["logs"], "last")
        self.assertEqual(tail["offset"], len(text) - 4)
        self.assertTrue(tail["truncated"])
        offset, chunks = 0, []
        while offset < len(text):
            result = page(text, offset=offset, max_chars=4)
            chunks.append(str(result["logs"]))
            next_offset = result["next_offset"]
            if next_offset is None:
                break
            assert isinstance(next_offset, int)
            offset = next_offset
        self.assertEqual("".join(chunks), text)
        self.assertIsNone(page(text, offset=999)["next_offset"])

    def test_redaction_precedes_slicing_and_handles_credentials_and_quoted_secrets(self) -> None:
        text = (
            'API_TOKEN="a secret with spaces"\n'
            'DB_PASSWORD=another-secret\n'
            'PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nkey-material\n-----END PRIVATE KEY-----\n'
            'https://user:url-password@example.test/path\n'
            'Authorization: Bearer bearer-secret\n'
            'configured-api-credential\nBuild failed'
        )
        redacted = str(page(text)["logs"])
        for secret in ("a secret with spaces", "another-secret", "key-material", "url-password",
                       "bearer-secret", "configured-api-credential"):
            self.assertNotIn(secret, redacted)
        self.assertIn("Build failed", redacted)
        self.assertEqual(page(text, offset=1, max_chars=12)["logs"], redacted[1:13])

    def test_invalid_windows_are_rejected_before_contacting_coolify(self) -> None:
        provider = client()
        with patch.object(provider._transport, "request") as request:
            for offset, max_chars in ((-1, 100), (None, 0), (None, 100_001)):
                with (
                    self.subTest(offset=offset, max_chars=max_chars),
                    self.assertRaises(ValueError),
                ):
                    provider.deployment_logs("id", offset=offset, max_chars=max_chars)
        request.assert_not_called()

    def test_malformed_structured_output_has_a_sanitized_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "entry.output must be a string") as raised:
            page([{"output": {"secret": "private-output"}}])
        self.assertNotIn("private-output", str(raised.exception))

    def test_journal_is_not_duplicated_in_management_audit(self) -> None:
        result = invocation_result_payload(
            "coolify", {"logs": "private-journal"}, "coolify_get_deployment_logs"
        )
        self.assertNotIn("private-journal", result)
        self.assertIn("omitted", result)
