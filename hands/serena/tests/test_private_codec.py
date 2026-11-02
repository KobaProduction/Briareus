"""The private relay retains exact requests and original MCP result fields."""

import json
import unittest
from uuid import UUID

from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError
from serena_hand.infrastructure.child_relay import bounded_json
from serena_hand.infrastructure.private_messages import PrivateRequest

from hand_runtime.provider_results import ProviderReply


class PrivateCodecTests(unittest.TestCase):
    def test_exact_request_rejects_missing_extra_and_non_boolean_background(self) -> None:
        valid = (
            '{"id":"b44f8bd6-430c-417b-b272-018d568f088c","tool":"find_symbol",'
            '"arguments":{},"expires_at":105}'
        )
        request = PrivateRequest.model_validate_json(valid)
        self.assertFalse(request.background)
        self.assertEqual(request.authority().expires_at, 105)
        for invalid in (
            valid.replace('"arguments":{},', ""),
            valid[:-1] + ',"extra":1}',
            valid[:-1] + ',"background":1}',
            valid.replace('"expires_at":105', '"expires_at":true'),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                PrivateRequest.model_validate_json(invalid)

    def test_original_mcp_wire_names_and_top_level_structure_are_preserved(self) -> None:
        result = CallToolResult(
            content=[TextContent(type="text", text="original")],
            structured_content={"value": 3},
            is_error=False,
        )
        identifier = UUID("b44f8bd6-430c-417b-b272-018d568f088c")
        encoded = bounded_json(ProviderReply(id=identifier, result=result))
        self.assertEqual(
            json.loads(encoded),
            {
                "id": str(identifier),
                "result": {
                    "content": [{"type": "text", "text": "original"}],
                    "structuredContent": {"value": 3},
                    "isError": False,
                    "resultType": "complete",
                },
            },
        )
