"""Human Web permits require current project rights and exact owner scope."""

import base64
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from authorization._human_web_effect import _human_call
from authorization.application.human_web import AuthorizeHumanEffect
from authorization.domain.human_web import (
    HumanCall,
    HumanDecision,
    HumanIdentity,
    HumanResource,
)
from authorization.domain.workspace_effects import WorkspaceBinding, WorkspaceIdentity
from authorization.infrastructure.call_journal import call_evidence, verified_call
from authorization.infrastructure.human_web_policy import CedarHumanPolicy
from authorization.infrastructure.human_web_signer import HumanEffectSigner
from node_protocol.control import canonical
from node_protocol.effect import HumanPermitVerifier
from node_protocol.module_effects import resource_id
from runtime_peer.human_web import HumanEffectInput


@dataclass
class Identities:
    initial: HumanIdentity
    refreshed: HumanIdentity
    calls: int = 0

    async def current(self) -> HumanIdentity:
        self.calls += 1
        return self.initial if self.calls == 1 else self.refreshed


@dataclass
class Binding:
    value: WorkspaceBinding

    async def current(self) -> WorkspaceBinding:
        return self.value


@dataclass
class Resources:
    value: HumanResource

    async def current(self, identity: HumanIdentity, binding: WorkspaceBinding) -> HumanResource:
        assert identity.project_uuid == binding.project_uuid
        return self.value


@dataclass
class AuthorityCase:
    now: datetime
    call: HumanCall
    identity: HumanIdentity
    binding: WorkspaceBinding
    signer: HumanEffectSigner
    body: bytes
    bearer: str

    def execute(
        self,
        *,
        identity: HumanIdentity | None = None,
        refreshed: HumanIdentity | None = None,
        scope: HumanResource | None = None,
    ) -> AuthorizeHumanEffect:
        return AuthorizeHumanEffect(
            identities=Identities(identity or self.identity, refreshed or self.identity),
            bindings=Binding(self.binding),
            resources=Resources(
                scope
                or HumanResource(
                    self.binding.resource_id,
                    frozenset(
                        {"local_browser_settings", "web_operation_start", "web_operation_poll"}
                    ),
                )
            ),
            policy=CedarHumanPolicy(),
            signer=self.signer,
            clock=lambda: self.now,
        )


def authority_case() -> AuthorityCase:
    now = datetime.now(UTC).replace(microsecond=0)
    project, node, placement, workspace, actor, request = (uuid4() for _ in range(6))
    body = canonical(
        {
            "jsonrpc": "2.0",
            "id": str(request),
            "method": "tools/call",
            "params": {"name": "local_browser_settings", "arguments": {"section": "settings"}},
        }
    )
    bearer = "Bearer browser-provider-fixture"
    signer = HumanEffectSigner(Ed25519PrivateKey.generate())
    resource = resource_id("web", node, project, workspace)
    return AuthorityCase(
        now,
        HumanCall(
            project,
            request,
            "tools/call",
            "local_browser_settings",
            None,
            hashlib.sha256(body).hexdigest(),
            hashlib.sha256(bearer.encode()).hexdigest(),
            hashlib.sha256(canonical({"section": "settings"})).hexdigest(),
        ),
        HumanIdentity(
            WorkspaceIdentity(
                "https://issuer.example",
                "human",
                actor,
                now + timedelta(seconds=30),
                now + timedelta(seconds=20),
            ),
            project,
            ("use_resources",),
        ),
        WorkspaceBinding(
            project,
            node,
            placement,
            workspace,
            8,
            "a" * 64,
            signer.public_key,
            int(now.timestamp()) + 5,
            resource,
            resource,
        ),
        signer,
        body,
        bearer,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["file_read", "file_write_text"])
async def test_human_files_uses_exact_current_project_scope_without_agent_session(
    tool: Literal["file_read", "file_write_text"],
) -> None:
    case = authority_case()
    arguments = {"path": "fixture.txt"}
    if tool == "file_write_text":
        arguments["content"] = "fixture"
    body = canonical(
        {
            "jsonrpc": "2.0",
            "id": str(case.call.request_uuid),
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    )
    call = _human_call(
        HumanEffectInput(
            module="files",
            project_uuid=case.call.project_uuid,
            request_uuid=case.call.request_uuid,
            bearer=SecretStr(case.bearer.removeprefix("Bearer ")),
            body=base64.b64encode(body).decode(),
        )
    )
    resource = resource_id(
        "files", case.binding.node_uuid, call.project_uuid, case.binding.workspace_uuid
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
    scope = HumanResource(resource, frozenset({tool}))
    encoded = await case.execute(scope=scope).execute(call)
    permit = HumanPermitVerifier(case.signer.public_key.encode()).verify(
        encoded,
        body=body,
        bearer=case.bearer,
        project_uuid=call.project_uuid,
    )
    assert permit.module == "files" and permit.tool == tool
    assert call.action == ("files.read" if tool == "file_read" else "files.write")
    assert "agent_session_uuid" not in permit.model_dump()
    with pytest.raises(PermissionError):
        await case.execute(scope=replace(scope, tools=frozenset({"file_info"}))).execute(call)


@pytest.mark.asyncio
async def test_human_browser_uses_current_rights_without_an_agent_grant() -> None:
    case = authority_case()
    encoded = await case.execute().execute(case.call)
    permit = HumanPermitVerifier(case.signer.public_key.encode()).verify(
        encoded,
        body=case.body,
        bearer=case.bearer,
        project_uuid=case.call.project_uuid,
    )
    assert permit.actor_uuid == case.identity.identity.actor_uuid
    assert permit.resource_revision == 8
    assert permit.expires_at - permit.issued_at == 5
    assert "agent_session_uuid" not in permit.model_dump()
    assert "grant_revision" not in permit.model_dump()
    evidence = call_evidence(verified_call(encoded, case.signer.key.public_key()))
    assert evidence.agent_session_uuid is None
    assert evidence.entity_uuid == case.binding.placement_uuid
    assert evidence.actor_uuid == case.identity.identity.actor_uuid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["rights", "expired", "project", "scope", "refreshed_rights", "actor"]
)
async def test_human_authority_fails_closed_when_current_proofs_change(change: str) -> None:
    case = authority_case()
    identity, refreshed = case.identity, case.identity
    scope = HumanResource(case.binding.resource_id, frozenset({"local_browser_settings"}))
    match change:
        case "rights":
            identity = replace(identity, permissions=())
        case "expired":
            identity = replace(
                identity, identity=replace(identity.identity, provider_expires_at=case.now)
            )
        case "project":
            identity = replace(identity, project_uuid=uuid4())
        case "scope":
            scope = replace(scope, resource_id="browser:" + "other" * 20)
        case "refreshed_rights":
            refreshed = replace(refreshed, permissions=())
        case "actor":
            refreshed = replace(refreshed, identity=replace(refreshed.identity, actor_uuid=uuid4()))
    with pytest.raises(PermissionError):
        await case.execute(identity=identity, refreshed=refreshed, scope=scope).execute(case.call)


@pytest.mark.asyncio
async def test_poll_requires_original_tool_scope_and_current_start_permission() -> None:
    case = authority_case()
    call = replace(case.call, tool="web_operation_poll", original_tool="local_browser_settings")
    scope = HumanResource(
        case.binding.resource_id, frozenset({"web_operation_poll", "web_operation_start"})
    )
    with pytest.raises(PermissionError):
        await case.execute(scope=scope).execute(call)
    with pytest.raises(ValueError, match="Exact original"):
        replace(call, original_tool="web_operation_start").required_tools()


@pytest.mark.parametrize(
    "project_access,owner_scope", [(False, True), (True, False), (False, False)]
)
@pytest.mark.parametrize("action", ["web.access", "files.read", "files.write"])
def test_cedar_requires_both_current_human_authorities(
    project_access: bool,
    owner_scope: bool,
    action: Literal["web.access", "files.read", "files.write", "terminal.execute", "analysis.import"],
) -> None:
    decision = HumanDecision(uuid4(), uuid4(), "fixture", project_access, owner_scope, action)
    assert not CedarHumanPolicy().permits(decision)
