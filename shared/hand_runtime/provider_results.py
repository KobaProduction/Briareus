"""Standard MCP results at the isolated provider's bounded IPC boundary."""

from __future__ import annotations

import json
from uuid import UUID

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict
from pydantic_core import to_jsonable_python


def provider_result(outcome: BaseModel) -> CallToolResult:
    if isinstance(outcome, CallToolResult):
        return outcome
    # First-party models are serialized once, at the MCP transport boundary.
    # RootModel over a concrete list/scalar need not serialize to an object.
    value: object = outcome.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=True, allow_nan=False)
    return CallToolResult(
        content=[TextContent(type="text", text=encoded)],
        structured_content=value if isinstance(value, dict) else None,
        is_error=False,
    )


def provider_failure(code: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=code)], is_error=True)


class ProviderReply(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    result: CallToolResult

    def encode(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="python", by_alias=True, exclude_none=True),
            default=to_jsonable_python,
            ensure_ascii=True,
            allow_nan=False,
        )
        if len(encoded.encode()) > 1_000_000:
            raise ValueError("Provider output exceeds budget")
        return encoded
