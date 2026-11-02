"""Provider IPC preserves real MCP SDK receipts instead of stringifying them twice."""

import json
import unittest
from uuid import UUID

from mcp.types import CallToolResult, ResourceLink, TextContent
from pydantic import BaseModel, JsonValue, RootModel

from hand_runtime.provider_results import ProviderReply, provider_failure, provider_result

REQUEST = UUID("53548f7b-787c-43ea-89b1-c497231bb9e3")


class Receipt(BaseModel):
    old_head_sha: str
    new_head_sha: str


class ProviderResultTests(unittest.TestCase):
    def test_sdk_history_receipt_retains_exact_native_mcp_fields(self) -> None:
        text = '{"old_head_sha":"old","new_head_sha":"new","mapping":{"old":"new"}}'
        structured: dict[str, JsonValue] = {
            "old_head_sha": "old",
            "new_head_sha": "new",
            "mapping": {"old": "new"},
        }
        sdk = CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=structured,
            is_error=False,
        )
        encoded = ProviderReply(id=REQUEST, result=provider_result(sdk)).encode()
        self.assertEqual(
            json.loads(encoded),
            {
                "id": str(REQUEST),
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "structuredContent": structured,
                    "isError": False,
                    "resultType": "complete",
                },
            },
        )

    def test_sdk_errors_remain_errors_and_content_is_not_reencoded(self) -> None:
        sdk = CallToolResult(
            content=[TextContent(type="text", text="native failure")],
            is_error=True,
        )
        result = json.loads(ProviderReply(id=REQUEST, result=provider_result(sdk)).encode())[
            "result"
        ]
        self.assertEqual(
            result,
            {
                "content": [{"type": "text", "text": "native failure"}],
                "isError": True,
                "resultType": "complete",
            },
        )

    def test_legacy_json_and_named_models_keep_the_original_payload_wrapper(self) -> None:
        receipt = Receipt(old_head_sha="old", new_head_sha="new")
        expected = {"old_head_sha": "old", "new_head_sha": "new"}
        result = json.loads(ProviderReply(id=REQUEST, result=provider_result(receipt)).encode())[
            "result"
        ]
        self.assertEqual(result["structuredContent"], expected)
        self.assertEqual(json.loads(result["content"][0]["text"]), expected)
        self.assertFalse(result["isError"])
        self.assertEqual(result["resultType"], "complete")

    def test_non_object_legacy_result_has_only_text_and_error_flag(self) -> None:
        receipt = RootModel[list[str | int]](["value", 0])
        result = json.loads(ProviderReply(id=REQUEST, result=provider_result(receipt)).encode())
        self.assertEqual(set(result["result"]), {"content", "isError", "resultType"})
        self.assertEqual(json.loads(result["result"]["content"][0]["text"]), ["value", 0])
        self.assertEqual(result["result"]["resultType"], "complete")

    def test_non_finite_results_and_output_over_budget_are_rejected(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            for nonfinite in (
                CallToolResult(content=[], structured_content={"invalid": value}),
                CallToolResult(content=[], meta={"invalid": value}),
            ):
                with (
                    self.subTest(value=value, metadata=nonfinite.meta is not None),
                    self.assertRaises(ValueError),
                ):
                    ProviderReply(id=REQUEST, result=provider_result(nonfinite)).encode()
        too_large = CallToolResult(content=[TextContent(type="text", text="a" * 1_000_001)])
        with self.assertRaisesRegex(ValueError, "Provider output exceeds budget"):
            ProviderReply(id=REQUEST, result=provider_result(too_large)).encode()

    def test_native_resource_links_keep_their_url_and_metadata(self) -> None:
        sdk = CallToolResult(
            content=[
                ResourceLink(type="resource_link", uri="https://example.com/blob", name="blob")
            ],
            meta={"progress": 1},
        )
        result = json.loads(ProviderReply(id=REQUEST, result=provider_result(sdk)).encode())[
            "result"
        ]
        self.assertEqual(result["content"][0]["uri"], "https://example.com/blob")
        self.assertEqual(result["_meta"], {"progress": 1})
        self.assertEqual(result["resultType"], "complete")

    def test_failure_codec_keeps_the_existing_fixed_safe_message(self) -> None:
        result = json.loads(
            ProviderReply(id=REQUEST, result=provider_failure("SVC_FAILED")).encode()
        )
        self.assertEqual(
            result,
            {
                "id": str(REQUEST),
                "result": {
                    "content": [{"type": "text", "text": "SVC_FAILED"}],
                    "isError": True,
                    "resultType": "complete",
                },
            },
        )
