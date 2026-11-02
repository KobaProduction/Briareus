"""Terminal users retain project authority without borrowing agent grants."""

import base64
from dataclasses import replace

import pytest
from pydantic import SecretStr
from test_human_web_authority import authority_case, canonical

from authorization._human_web_effect import _human_call
from authorization.domain.human_web import HumanResource
from node_protocol.effect import HumanPermitVerifier
from node_protocol.terminal import workspace_resource
from runtime_peer.human_web import HumanEffectInput


@pytest.mark.asyncio
async def test_human_terminal_requires_exact_current_workspace_and_tool() -> None:
    case = authority_case()
    body = canonical(
        {
            "jsonrpc": "2.0",
            "id": str(case.call.request_uuid),
            "method": "tools/call",
            "params": {"name": "terminal_status", "arguments": {}},
        }
    )
    call = _human_call(
        HumanEffectInput(
            module="terminal",
            project_uuid=case.call.project_uuid,
            request_uuid=case.call.request_uuid,
            bearer=SecretStr(case.bearer.removeprefix("Bearer ")),
            body=base64.b64encode(body).decode(),
        )
    )
    resource = workspace_resource(
        case.binding.node_uuid,
        call.project_uuid,
        case.binding.workspace_uuid,
    )
    case = replace(
        case,
        call=call,
        body=body,
        binding=replace(
            case.binding,
            resource_id=resource,
            canonical_resource_id=resource,
        ),
    )
    scope = HumanResource(resource, frozenset({"terminal_status"}))
    encoded = await case.execute(scope=scope).execute(call)
    permit = HumanPermitVerifier(case.signer.public_key.encode()).verify(
        encoded,
        body=body,
        bearer=case.bearer,
        project_uuid=call.project_uuid,
    )
    assert permit.module == "terminal"
    assert call.action == "terminal.execute"
    assert "agent_session_uuid" not in permit.model_dump()
    assert "grant_revision" not in permit.model_dump()
    with pytest.raises(PermissionError):
        await case.execute(scope=replace(scope, tools=frozenset({"job_start"}))).execute(call)
