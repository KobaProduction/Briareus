"""Real stateless SDK HTTP dispatch must finish within its signed effect lease."""

import asyncio
import time
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastmcp import FastMCP
from mcp.types import CallToolRequestParams, CallToolResult, TextContent

from hand_runtime.node_adapter import NodeDelegatedTool
from hand_runtime.node_boundary import EffectBoundary
from hand_runtime.tool_binding import bind_delegated_tool
from node_protocol.effect import (
    EffectPermit,
    EffectVerifier,
    HumanEffectPermit,
    NodeEffectPermit,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("human", [False, True])
async def test_signed_delegated_http_call_finishes_before_lease_expiry(human: bool) -> None:
    server: FastMCP[None] = FastMCP("node-http-boundary")

    @server.tool
    def fixture_echo(value: str) -> str:
        return value

    now = int(time.time())
    permit: EffectPermit = NodeEffectPermit(
        module="web",
        node_uuid=uuid4(),
        placement_uuid=uuid4(),
        project_uuid=uuid4(),
        workspace_uuid=uuid4(),
        actor_uuid=uuid4(),
        agent_session_uuid=uuid4(),
        request_uuid=uuid4(),
        grant_revision=1,
        fingerprint="a" * 64,
        body_digest="b" * 64,
        bearer_digest="c" * 64,
        arguments_digest="d" * 64,
        method="tools/call",
        tool="fixture_echo",
        resource_id="fixture:" + "x" * 80,
        issued_at=now,
        expires_at=now + 10,
    )
    if human:
        permit = HumanEffectPermit.model_validate(
            {
                **permit.model_dump(exclude={"agent_session_uuid", "grant_revision"}),
                "human": True,
                "resource_revision": 1,
            }
        )
    executed: list[str] = []

    async def execute(call: CallToolRequestParams, _permit: NodeEffectPermit) -> CallToolResult:
        executed.append("agent:" + call.name)
        return CallToolResult(content=[TextContent(type="text", text="completed")])

    async def execute_human(
        call: CallToolRequestParams, _permit: HumanEffectPermit
    ) -> CallToolResult:
        executed.append("human:" + call.name)
        return CallToolResult(content=[TextContent(type="text", text="completed")])

    original = (await server.list_tools())[0]
    runner = NodeDelegatedTool(original.name, execute, "web", execute_human)
    server.add_tool(bind_delegated_tool(original, runner.run))
    app = server.http_app(stateless_http=True, json_response=True, host_origin_protection=False)
    verifier = Mock(spec=EffectVerifier)
    verifier.verify.return_value = permit
    boundary = EffectBoundary(app, verifier)
    # The original request, rather than SDK-injected defaults, is authorized.
    import hashlib

    from node_protocol.control import canonical

    arguments = {"value": "fixture"}
    permit = permit.model_copy(
        update={"arguments_digest": hashlib.sha256(canonical(arguments)).hexdigest()}
    )
    verifier.verify.return_value = permit
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(boundary), base_url="http://localhost"
        ) as client,
    ):
        async with asyncio.timeout(3):
            response = await client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer fixture",
                    "X-Briareus-Node-Permit": "fixture",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-03-26",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": "fixture",
                    "method": "tools/call",
                    "params": {"name": "fixture_echo", "arguments": arguments},
                },
            )
    assert response.status_code == 200
    assert response.json()["result"]["content"][0]["text"] == "completed"
    assert executed == [("human:" if human else "agent:") + "fixture_echo"]
    verifier.verify.assert_called_once()
