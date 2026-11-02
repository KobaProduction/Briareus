"""Translate native analysis documents only at the MCP transport boundary."""

import json
from typing import Literal

from fastmcp.client.client import CallToolResult as ClientCallToolResult
from fastmcp.tools import ToolResult
from mcp.types import CallToolResult, TextContent

from .terminology import (
    analysis_group_name,
    analysis_result_key,
    analysis_result_text,
    analysis_text,
    analysis_tool_name,
)


def _unwrap_result_envelope(result: CallToolResult) -> bool:
    envelope = result.structured_content
    if envelope is None or "result" not in envelope:
        raise ValueError("Analysis provider envelope required")
    value = envelope["result"]
    if isinstance(value, dict) and "result" in value:
        nested = value["result"]
        if nested is value:
            return False
        envelope["result"] = nested
        return True
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            return False
        if decoded == value:
            return False
        envelope["result"] = decoded
        return True
    return False


def _decode_candidate(
    result: ClientCallToolResult,
    origin: Literal["structured", "data", "text"],
    *,
    text_index: int = 0,
) -> CallToolResult | None:
    # Raw SDK fields are consumed only by this input decoder.
    structured, data = result.structured_content, result.data
    value = data
    if origin == "structured":
        value = structured
    elif origin == "text":
        block = result.content[text_index]
        if not isinstance(block, TextContent):
            return None
        value = block.text
    candidate = CallToolResult(content=[], structured_content={"result": value})
    for _ in range(8):
        if not _unwrap_result_envelope(candidate):
            break
    envelope = candidate.structured_content
    if envelope is None or envelope["result"] is None:
        return None
    # Copy before translating so the private client's reply is unchanged.
    envelope["result"] = json.loads(
        json.dumps(envelope["result"], ensure_ascii=True, allow_nan=False)
    )
    return adapt_analysis_result(candidate)


def decode_call_result(result: ClientCallToolResult) -> CallToolResult | None:
    """Keep structured/data/text precedence and the eight-envelope decode bound."""
    decoded = _decode_candidate(result, "structured")
    if decoded is not None:
        return decoded
    decoded = _decode_candidate(result, "data")
    if decoded is not None:
        return decoded
    for index, block in enumerate(result.content):
        if isinstance(block, TextContent):
            decoded = _decode_candidate(result, "text", text_index=index)
            if decoded is not None:
                return decoded
    return None


def _public_text(text: str, key: str | None) -> str:
    if key == "tools":
        return analysis_tool_name(text)
    if key == "group":
        return analysis_group_name(text)
    if key in {"description", "title"}:
        return analysis_text(text)
    return analysis_result_text(text, key)


def _translate_result_step(pending: list[tuple[object, str | None]]) -> None:
    container, parent_key = pending.pop()
    if isinstance(container, dict):
        entries = tuple(container.items())
        container.clear()
        for key, item in entries:
            public_key = analysis_result_key(key)
            container[public_key] = (
                _public_text(item, public_key) if isinstance(item, str) else item
            )
            pending.append((container[public_key], public_key))
    elif isinstance(container, list):
        for index, item in enumerate(container):
            if isinstance(item, str):
                container[index] = _public_text(item, parent_key)
            else:
                pending.append((item, parent_key))


def adapt_analysis_result(result: CallToolResult) -> CallToolResult:
    """Retain arbitrary provider columns inside the final standard MCP reply."""
    envelope = result.structured_content
    if envelope is None or "result" not in envelope:
        raise ValueError("Decoded analysis provider document required")
    document = [envelope["result"]]
    pending: list[tuple[object, str | None]] = [(document, None)]
    while pending:
        _translate_result_step(pending)
    converted = ToolResult(
        content=document[0],
        structured_content={"result": document[0]},
        meta={"fastmcp": {"wrap_result": True}},
    )
    return CallToolResult(
        content=converted.content,
        structured_content=converted.structured_content,
        meta=converted.meta,
        is_error=converted.is_error,
    )
