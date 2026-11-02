"""Current human Analysis scope includes ownership-safe operation continuation."""

import base64
from dataclasses import replace

import pytest
from pydantic import SecretStr
from test_human_web_authority import authority_case

from authorization._human_web_effect import _human_call
from authorization.domain.human_web import HumanResource
from node_protocol.control import canonical
from node_protocol.effect import HumanPermitVerifier
from node_protocol.module_effects import resource_id
from runtime_peer.human_web import HumanEffectInput


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool", ["analysis_tools", "analysis_start", "analysis_poll", "analysis_cancel"]
)
async def test_human_analysis_uses_current_project_scope_and_continuation_tool(tool: str) -> None:
    case = authority_case()
    body = canonical(
        {
            "jsonrpc": "2.0",
            "id": str(case.call.request_uuid),
            "method": "tools/call",
            "params": {"name": tool, "arguments": {}},
        }
    )
    call = _human_call(
        HumanEffectInput(
            module="reverse",
            project_uuid=case.call.project_uuid,
            request_uuid=case.call.request_uuid,
            bearer=SecretStr(case.bearer.removeprefix("Bearer ")),
            body=base64.b64encode(body).decode(),
        )
    )
    resource = resource_id(
        "reverse",
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
    scope = HumanResource(resource, frozenset({tool, "analysis_start"}))
    encoded = await case.execute(scope=scope).execute(call)
    permit = HumanPermitVerifier(case.signer.public_key.encode()).verify(
        encoded,
        body=body,
        bearer=case.bearer,
        project_uuid=call.project_uuid,
    )
    assert permit.module == "reverse"
    assert call.action == "analysis.import"
    assert "agent_session_uuid" not in permit.model_dump()
    assert "grant_revision" not in permit.model_dump()
    if tool in {"analysis_poll", "analysis_cancel"}:
        with pytest.raises(PermissionError):
            await case.execute(scope=replace(scope, tools=frozenset({tool}))).execute(call)
