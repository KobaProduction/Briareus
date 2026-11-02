"""Decode SDK protocol metadata and validate owned receipts before releasing facts."""

import json
import re
from dataclasses import fields

from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, TypeAdapter

from control_panel_api.application.module_contracts import McpExchangeResult
from control_panel_api.domain.module_preparation import ModuleInitialization, PreparationEvidence
from runtime_peer.browser_receipts import BrowserPreparingReceipt, BrowserStatus
from runtime_peer.file_receipts import FILE_RESULTS
from runtime_peer.terminal_receipts import TERMINAL_RESULTS, TerminalReceipt, TerminalStatus

from .browser_codec import browser_reply
from .module_replies import NativeToolReply


class _InitializationHeader(BaseModel):
    # Capability documents remain protocol metadata and never confer permissions.
    model_config = ConfigDict(extra="ignore", frozen=True)
    protocolVersion: str | None = None


def decode_initialization(value: object) -> ModuleInitialization:
    if not isinstance(value, dict):
        raise ValueError("MCP initialization result required")
    for field in ("capabilities", "serverInfo"):
        if value.get(field) is not None and not isinstance(value[field], dict):
            raise ValueError("MCP initialization metadata must be an object")
    header = _InitializationHeader.model_validate(value)
    return ModuleInitialization(header.protocolVersion)


def _evidence(value: object, *, is_error: bool, node_preparing: bool) -> PreparationEvidence:
    while isinstance(value, dict) and set(value) == {"result"}:
        value = value["result"]
    if not isinstance(value, dict):
        return PreparationEvidence(is_error, node_preparing)
    engine = value.get("engine")
    return PreparationEvidence(
        is_error,
        node_preparing,
        value.get("running") is True,
        isinstance(value.get("workspace_root"), str),
        engine if isinstance(engine, str) else None,
        isinstance(value.get("tools"), list),
    )


def _text_evidence(
    messages: tuple[str, ...], *, is_error: bool, preparing: bool
) -> PreparationEvidence:
    for message in messages:
        try:
            return _evidence(json.loads(message), is_error=is_error, node_preparing=preparing)
        except ValueError:
            pass
    return PreparationEvidence(is_error, preparing)


def _tool_evidence(reply: CallToolResult, module: str | None = None) -> PreparationEvidence:
    messages = tuple(entry.text for entry in reply.content if isinstance(entry, TextContent))
    preparing = bool(re.search(r"\bNODE_PREPARING\b", "\n".join(messages)))
    content = reply.structured_content
    if content is None:
        return _text_evidence(messages, is_error=reply.is_error, preparing=preparing)
    if module == "terminal":
        return PreparationEvidence(
            is_error=reply.is_error,
            node_preparing=preparing,
            workspace_ready=isinstance(content, TerminalStatus),
        )
    if module == "web":
        return PreparationEvidence(
            is_error=reply.is_error,
            node_preparing=preparing,
            running=isinstance(content, BrowserStatus) and content.running,
            pending_operation=isinstance(content, BrowserPreparingReceipt)
            and content.result.pending is not None,
        )
    if module == "files":
        return PreparationEvidence(is_error=reply.is_error, node_preparing=preparing)
    return _evidence(content, is_error=reply.is_error, node_preparing=preparing)


def decode_mcp_reply(
    value: object, *, module: str | None = None, tool: str | None = None
) -> McpExchangeResult[NativeToolReply]:
    reply = CallToolResult.model_validate(value)
    if module == "terminal" and tool is not None:
        reply = terminal_reply(reply, tool)
    elif module == "files" and tool is not None:
        reply = files_reply(reply, tool)
    elif module == "web" and tool is not None:
        reply = browser_reply(reply, tool)
    evidence = _tool_evidence(reply, module if tool is not None else None)
    return McpExchangeResult(reply, evidence)


def terminal_reply(reply: CallToolResult, tool: str) -> CallToolResult:
    content = reply.structured_content
    if content is None:
        return reply
    receipt_type = TERMINAL_RESULTS[tool]
    expected = {field.name for field in fields(receipt_type)}
    if not isinstance(content, dict) or set(content) != expected:
        raise ValueError("Exact Terminal receipt fields required")
    receipt = TypeAdapter[TerminalReceipt](receipt_type).validate_python(content)
    return reply.model_copy(update={"structured_content": receipt})


def files_reply(reply: CallToolResult, tool: str) -> CallToolResult:
    content = reply.structured_content
    if content is None:
        return reply
    receipt = FILE_RESULTS[tool].model_validate(content)
    return reply.model_copy(update={"structured_content": receipt})
