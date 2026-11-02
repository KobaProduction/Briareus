"""Decode private MCP SDK replies into a consumer's concrete transport model."""

import json

from fastmcp.client.client import CallToolResult
from mcp.types import TextContent
from pydantic import BaseModel, StrictBool, StrictStr


class _ProviderStatus(BaseModel):
    error: StrictStr | None = None
    success: StrictBool | None = None

    def require_success(self, context: str) -> None:
        if self.error and self.error.strip():
            raise ValueError(self.error.strip())
        if self.success is False:
            raise ValueError(f"{context} failed")


def _candidate_reply[T: BaseModel](
    value: object, response_type: type[T], *, context: str, unwrap_data: bool, is_error: bool
) -> T | None:
    # Raw SDK values never leave this transport adapter.
    for _ in range(8):
        if isinstance(value, dict) and "result" in value:
            value = value["result"]
        elif unwrap_data and isinstance(value, dict) and "data" in value:
            value = value["data"]
        elif isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                break
        else:
            break
    if value is None:
        return None
    if isinstance(value, dict):
        _ProviderStatus.model_validate(value).require_success(context)
    if is_error:
        raise ValueError(f"{context} failed")
    # JSON validation retains Pydantic's JSON-mode datetime/UUID semantics.
    return response_type.model_validate_json(json.dumps(value, ensure_ascii=False, allow_nan=False))


def decode_mcp_reply[T: BaseModel](
    result: CallToolResult,
    response_type: type[T],
    *,
    context: str,
    unwrap_data: bool = True,
) -> T:
    candidates: list[object] = [result.structured_content, result.data]
    candidates.extend(block.text for block in result.content if isinstance(block, TextContent))
    for candidate in candidates:
        if candidate is None:
            continue
        reply = _candidate_reply(
            candidate,
            response_type,
            context=context,
            unwrap_data=unwrap_data,
            is_error=result.is_error,
        )
        if reply is not None:
            return reply
    raise ValueError(f"{context} returned no result")
