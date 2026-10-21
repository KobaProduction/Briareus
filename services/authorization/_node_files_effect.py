"""Issue workspace execution evidence after current identity, owner and Cedar checks."""
import asyncio
import base64
import hashlib
import time
from dataclasses import replace
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, UUID4

from authorization._decision_api import DecisionCommand, AuthorizationDecisionReader, VerifiedDecisionCaller
from authorization._mcp_admission_runtime import AdmissionInput, current_identity,CurrentProjectDenied
from authorization._rauthy_jwks import RauthyTokenRejected
from authorization._resource_scope import EffectResource
from node_protocol.control import canonical
from node_protocol.effect import NodeWorkspaceBinding, NodeEffectPermit, sign_permit
from node_protocol.module_effects import MODULES, RESOURCE_KINDS, TOOL_NAME, parse_request, resource_id, effect_action


class WorkspaceEffectInput(AdmissionInput):
    node_uuid: UUID4
    placement_uuid: UUID4
    request_uuid: UUID4
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    body: str = Field(min_length=1, max_length=43692)


def node_workspace_effect_router(*, module, platform, resources, resolve_database, actor_model, issuers, signing_key):
    if module not in MODULES:
        raise ValueError("Approved Node module effect adapter required")
    router = APIRouter()

    def answer(status, code):
        code = code.replace("FILES_", module.upper() + "_")
        return JSONResponse({"code": code}, status_code=status, headers={"Cache-Control": "no-store"})

    @router.post("/internal/v1/authorization/node-" + module + "-effect", include_in_schema=False)
    async def authorize(request: Request):
        if request.scope.get("briareus.service_peer") != "briareus:gateway":
            return answer(403, "GATEWAY_PEER_REQUIRED")
        try:
            command = WorkspaceEffectInput.model_validate(await request.json())
            if command.module != module or command.decision.action != "mcp.connect":
                raise ValueError("Files connection selectors required")
            body = base64.b64decode(command.body, validate=True)
            frame = parse_request(module, body)
        except (ValueError, TypeError):
            return answer(422, "FILES_EFFECT_INVALID")
        database, keys = resolve_database(), issuers.get(module)
        if database is None or keys is None or resources is None or signing_key is None:
            return answer(503, "FILES_AUTHORITY_UNAVAILABLE")
        try:
            async with asyncio.timeout(4):
                actor, signed = await current_identity(platform=platform, actor_model=actor_model, keys=keys,
                    bearer=command.bearer.get_secret_value(), project_uuid=command.decision.project_uuid)
                status, result = await resources.call("/internal/v1/resources/node-" + module + "-authority", {
                    "project_uuid": str(command.decision.project_uuid), "module": module})
                if status != 200 or not isinstance(result, dict) or set(result) != {"binding"}:
                    raise ValueError("Current Files binding unavailable")
                binding = NodeWorkspaceBinding.model_validate(result["binding"])
                public_key = signing_key.public_key().public_bytes(serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo).decode()
                now = int(time.time())
                if (binding.project_uuid != command.decision.project_uuid or binding.node_uuid != command.node_uuid
                    or binding.placement_uuid != command.placement_uuid or binding.fingerprint != command.fingerprint
                    or binding.effect_verify_key != public_key or not now < binding.expires_at <= now + 5
                    or binding.resource_id != resource_id(module, binding.node_uuid, binding.project_uuid, binding.workspace_uuid)):
                    raise ValueError("Current Files binding mismatch")
                decision = command.decision
                if frame.tool is not None:
                    decision = DecisionCommand(project_uuid=decision.project_uuid,
                        agent_session_uuid=decision.agent_session_uuid, expected_grant_revision=decision.expected_grant_revision,
                        action=effect_action(module, frame.tool), hand=module, tool=frame.tool,
                        resource=EffectResource(kind=RESOURCE_KINDS[module], id=binding.resource_id))
                caller = VerifiedDecisionCaller(actor_uuid=actor.actor_uuid, project_uuid=decision.project_uuid,
                    agent_session_uuid=decision.agent_session_uuid, consumer="hand" if frame.tool else "gateway",
                    authority="rauthy", verified_peer_audience="briareus:access",
                    proof_expires_at=min(actor.expires_at, signed.expires_at,
                        datetime.fromtimestamp(binding.expires_at, UTC)), attested_effect_key=decision.effect_key())
                current = await AuthorizationDecisionReader(database).current_grant(decision, caller)
                if current is None:
                    return answer(403, "FILES_CURRENT_CEDAR_GRANT_REQUIRED")
                if module == "reverse" and frame.tool == "analysis_poll":
                    # A poll resumes the original native effect. A poll-only
                    # grant must never bypass revocation of start authority.
                    start_decision = decision.model_copy(update={"tool": "analysis_start"})
                    start_caller = replace(caller, attested_effect_key=start_decision.effect_key())
                    start_current = await AuthorizationDecisionReader(database).current_grant(start_decision, start_caller)
                    if start_current is None or start_current.grant_revision != current.grant_revision:
                        return answer(403, "FILES_CURRENT_CEDAR_GRANT_REQUIRED")
                    current = replace(current, expires_at=min(current.expires_at, start_current.expires_at))
                if module in {"web","serena","svc","infrastructure"} and frame.tool in {module+"_operation_start",module+"_operation_poll"}:
                    original_tool = frame.arguments.get("tool")
                    if (not isinstance(original_tool,str) or not TOOL_NAME.fullmatch(original_tool)
                        or original_tool.startswith(module+"_operation_")):
                        raise ValueError("Actual original module tool required")
                    required = [original_tool]
                    if frame.tool == module+"_operation_poll":
                        required.append(module+"_operation_start")
                    for tool in required:
                        original = decision.model_copy(update={"tool":tool})
                        original_caller = replace(caller,attested_effect_key=original.effect_key())
                        authorized = await AuthorizationDecisionReader(database).current_grant(original,original_caller)
                        if authorized is None or authorized.grant_revision != current.grant_revision:
                            return answer(403,"FILES_CURRENT_CEDAR_GRANT_REQUIRED")
                        current = replace(current,expires_at=min(current.expires_at,authorized.expires_at))
                context_raw, context_reply = b"", {}
                context_expiry = binding.expires_at
                if module in {"svc", "infrastructure"} and frame.tool is not None:
                    status, context_reply = await resources.call("/internal/v1/resources/node-invocation", {
                        "issuer": signed.issuer, "subject": signed.subject,
                        "actor_uuid": str(actor.actor_uuid), "project_uuid": str(binding.project_uuid),
                        "agent_session_uuid": str(decision.agent_session_uuid), "grant_revision": current.grant_revision,
                        "identity_expires_at": min(actor.expires_at, signed.expires_at,
                            current.expires_at, datetime.fromtimestamp(binding.expires_at, UTC)).isoformat(),
                        "module": module, "tool": frame.tool, "arguments": frame.arguments,
                        "binding": binding.model_dump(mode="json")})
                    if status == 403:
                        return answer(403, "MCP_CURRENT_PROJECT_ACCOUNT_REQUIRED")
                    if (status != 200 or not isinstance(context_reply, dict)
                        or set(context_reply) != {"context", "expires_at"}
                        or not isinstance(context_reply["context"], dict)
                        or set(context_reply["context"]) - {"accounts", "policies"}
                        or not isinstance(context_reply["context"].get("accounts"), list)
                        or type(context_reply["expires_at"]) is not int
                        or not time.time() < context_reply["expires_at"] <= binding.expires_at):
                        raise ValueError("Current private invocation owner unavailable")
                    context_raw = canonical(context_reply["context"])
                    if not 0 < len(context_raw) <= 8192:
                        raise ValueError("Bounded private invocation context required")
                    context_expiry = context_reply["expires_at"]
                now = int(time.time())
                expiry = min(now + 5, int(current.expires_at.timestamp()), binding.expires_at, context_expiry)
                if expiry <= now:
                    raise ValueError("Files authority expired")
                permit = NodeEffectPermit(module=module, node_uuid=binding.node_uuid, placement_uuid=binding.placement_uuid,
                    project_uuid=binding.project_uuid, workspace_uuid=binding.workspace_uuid,
                    actor_uuid=actor.actor_uuid, agent_session_uuid=decision.agent_session_uuid,
                    request_uuid=command.request_uuid, grant_revision=current.grant_revision,
                    fingerprint=binding.fingerprint, body_digest=hashlib.sha256(body).hexdigest(),
                    bearer_digest=hashlib.sha256(("Bearer " + command.bearer.get_secret_value()).encode()).hexdigest(),
                    arguments_digest=hashlib.sha256(canonical(frame.arguments)).hexdigest(),
                    method=frame.method, tool=frame.tool, resource_id=binding.resource_id,
                    issued_at=now, expires_at=expiry,
                    context_digest=hashlib.sha256(context_raw).hexdigest() if context_raw else "")
                reply = {"permit": sign_permit(permit, signing_key)}
                if context_raw:
                    reply["context"] = base64.b64encode(context_raw).decode("ascii")
                return JSONResponse(reply, headers={"Cache-Control": "no-store"})
        except RauthyTokenRejected:
            return answer(401, "MCP_PROVIDER_BEARER_REJECTED")
        except CurrentProjectDenied:
            return answer(403,"MCP_CURRENT_PROJECT_REQUIRED")
        except Exception:
            # No provider tokens, request paths or upstream errors leave this private boundary.
            return answer(503, "FILES_AUTHORITY_UNAVAILABLE")

    return router


def node_files_effect_router(**kwargs):
    return node_workspace_effect_router(module="files", **kwargs)
