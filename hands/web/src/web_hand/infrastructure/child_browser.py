"""Bounded stdio transport for original browser tool invocations."""

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import ClientTransport
from mcp.types import CallToolResult

from web_hand.domain.child_profile import ChildProfile
from web_hand.infrastructure.browser_ipc import BrowserCatalogue, BrowserCommand, BrowserReply
from web_hand.node_runtime import STATIC_TOOLS, BrowserRuntime, browser_metadata

_EXTERNAL_CONTROLS = frozenset(
    {"external_status", "external_connect", "external_disconnect", "external_reset"}
)


def _write(value: str) -> None:
    sys.stdout.write(value + "\n")
    sys.stdout.flush()


def encode_reply(reply: BrowserReply) -> str:
    # Keep the existing three result fields when no SDK metadata was supplied.
    excluded = (
        {"result": {"meta"}} if reply.result is not None and reply.result.meta is None else None
    )
    payload = reply.model_dump(mode="json", by_alias=True, exclude=excluded)
    payload.pop("error" if reply.result is not None else "result")
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    if len(encoded) > 1000000:
        return BrowserReply(id=reply.id, error="WEB_OUTPUT_LIMIT").model_dump_json(
            exclude_none=True
        )
    return encoded


async def announce[Transport: ClientTransport](client: Client[Transport]) -> frozenset[str]:
    tools = browser_metadata(await client.list_tools())
    allowed = frozenset(tool.name for tool in tools)
    if not allowed >= STATIC_TOOLS or len(allowed) > 256:
        raise ValueError("Existing browser tool catalogue unavailable")
    catalogue = BrowserCatalogue(ready=True, tools=tools)
    encoded = json.dumps(
        catalogue.model_dump(mode="json", by_alias=True), separators=(",", ":"), ensure_ascii=True
    )
    if len(encoded) > 750000:
        raise ValueError("Browser metadata exceeds private IPC limit")
    _write(encoded)
    return allowed


def bind_profile(command: BrowserCommand, runtime: BrowserRuntime) -> None:
    ChildProfile(command.profile).require_selected()
    parent = Path(command.profile)
    if runtime.browser.profile_dir == parent / "profile":
        return
    if parent.is_symlink():
        raise ValueError("Private browser profile required")
    parent.mkdir(mode=0o700, exist_ok=True)
    runtime.browser.bind_unstarted_profile(
        parent / "profile",
        developer_access_enabled=os.environ.get("BRIAREUS_NODE_WEB_DEVELOPER_ACCESS") == "1",
    )


async def invoke[Transport: ClientTransport](
    client: Client[Transport], runtime: BrowserRuntime, command: BrowserCommand
) -> BrowserReply:
    try:
        call = command.call
        if call.name.startswith("external_") and call.name not in _EXTERNAL_CONTROLS:
            upstream = call.model_copy(update={"name": call.name[9:]})
            result = await runtime.external.guarded_call(upstream)
        else:
            result = await client.call_tool(call.name, call.arguments, raise_on_error=False)
        return BrowserReply(
            id=command.id,
            result=CallToolResult(
                content=result.content,
                structured_content=result.structured_content,
                is_error=result.is_error,
                meta=result.meta,
            ),
        )
    except Exception:
        return BrowserReply(id=command.id, error="WEB_OPERATION_FAILED")


async def relay[Transport: ClientTransport](
    client: Client[Transport], runtime: BrowserRuntime, allowed: frozenset[str]
) -> None:
    while True:
        line = await asyncio.to_thread(sys.stdin.buffer.readline, 65537)
        if not line:
            return
        if len(line) > 65536 or not line.endswith(b"\n"):
            raise ValueError("Browser supervisor command exceeds input limit")
        command = BrowserCommand.model_validate_json(line)
        if command.call.name not in allowed:
            raise ValueError("Invalid browser supervisor command")
        bind_profile(command, runtime)
        _write(encode_reply(await invoke(client, runtime, command)))
