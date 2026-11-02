"""HTTP composition of one current, resource-bound Node workspace effect."""

import asyncio
import base64
import hashlib
from collections.abc import Callable
from functools import partial
from operator import is_

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import UUID4, BaseModel, Field

from authorization._decision_api import AuthorizationDecisionReader
from authorization._mcp_admission_runtime import (
    AdmissionInput,
    CurrentProjectDenied,
    current_identity,
)
from authorization._rauthy_jwks import RauthyTokenRejected
from authorization.application.workspace_effects import AuthorizeWorkspaceEffect
from authorization.domain.workspace_effects import WorkspaceCall, WorkspaceGrantDenied
from authorization.infrastructure.mcp_identity import PeerWorkspaceIdentity
from authorization.infrastructure.mcp_issuers import McpIssuerRegistry
from authorization.infrastructure.workspace_effects import (
    InvocationAccountDenied,
    NodeWorkspaceEffectSigner,
    PeerPrivateInvocation,
    PeerWorkspaceBinding,
    SqlWorkspaceGrant,
)
from authorization.presentation.runtime_protocol import ActorContext
from authorization.presentation.source_control_effects import source_delegation
from common.platform_db import PlatformDatabase
from node_protocol.domain.mcp_request import McpRequestFacts
from node_protocol.module_effects import MODULES, parse_request
from runtime_peer import PeerClient


class WorkspaceEffectInput(AdmissionInput):
    node_uuid: UUID4
    placement_uuid: UUID4
    request_uuid: UUID4
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    body: str = Field(min_length=1, max_length=43692)


_no_context: Callable[[str | None], bool] = partial(is_, None)


class WorkspacePermitResponse(BaseModel):
    permit: str
    context: str | None = Field(default=None, exclude_if=_no_context)


def _workspace_call(
    command: WorkspaceEffectInput, frame: McpRequestFacts, body: bytes
) -> WorkspaceCall:
    decision = command.decision
    return WorkspaceCall(
        command.module,
        decision.project_uuid,
        decision.agent_session_uuid,
        command.node_uuid,
        command.placement_uuid,
        command.request_uuid,
        command.fingerprint,
        frame.method,
        frame.tool,
        frame.original_tool,
        decision.expected_grant_revision,
        hashlib.sha256(body).hexdigest(),
        hashlib.sha256(("Bearer " + command.bearer.get_secret_value()).encode()).hexdigest(),
        frame.arguments_digest,
        source_delegation(frame.tool, frame.original_tool, body)
        if command.module == "svc"
        else None,
    )


class WorkspaceEffectController:
    def __init__(
        self,
        *,
        module: str,
        platform: PeerClient,
        resources: PeerClient | None,
        resolve_database: Callable[[], PlatformDatabase | None],
        actor_model: type[ActorContext],
        issuers: McpIssuerRegistry,
        signing_key: Ed25519PrivateKey | None,
    ) -> None:
        if module not in MODULES:
            raise ValueError("Approved Node module effect adapter required")
        self.module = module
        self.platform = platform
        self.resources = resources
        self.resolve_database = resolve_database
        self.actor_model = actor_model
        self.issuers = issuers
        self.signing_key = signing_key

    def _answer(self, status: int, code: str) -> JSONResponse:
        return JSONResponse(
            {"code": code.replace("FILES_", self.module.upper() + "_")},
            status_code=status,
            headers={"Cache-Control": "no-store"},
        )

    async def authorize(self, request: Request) -> JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:gateway":
            return self._answer(403, "GATEWAY_PEER_REQUIRED")
        try:
            command = WorkspaceEffectInput.model_validate(await request.json())
            if command.module != self.module or command.decision.action != "mcp.connect":
                raise ValueError("Files connection selectors required")
            body = base64.b64decode(command.body, validate=True)
            frame = parse_request(self.module, body)
        except (ValueError, TypeError):
            return self._answer(422, "FILES_EFFECT_INVALID")
        database, keys = self.resolve_database(), self.issuers.get(self.module)
        if database is None or keys is None or self.resources is None or self.signing_key is None:
            return self._answer(503, "FILES_AUTHORITY_UNAVAILABLE")
        try:
            call = _workspace_call(command, frame, body)
            use_case = AuthorizeWorkspaceEffect(
                identities=PeerWorkspaceIdentity(
                    platform=self.platform,
                    actor_model=self.actor_model,
                    keys=keys,
                    bearer=command.bearer.get_secret_value(),
                    project_uuid=call.project_uuid,
                    resolver=current_identity,
                ),
                bindings=PeerWorkspaceBinding(self.resources, call),
                grants=SqlWorkspaceGrant(AuthorizationDecisionReader(database), call),
                invocations=PeerPrivateInvocation(self.resources, call, body),
                signer=NodeWorkspaceEffectSigner(self.signing_key),
                public_key=self.signing_key.public_key()
                .public_bytes(
                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                )
                .decode(),
            )
            async with asyncio.timeout(4):
                result = await use_case.execute(call)
            response = WorkspacePermitResponse(
                permit=result.permit,
                context=base64.b64encode(result.private_context).decode("ascii")
                if result.private_context
                else None,
            )
            return JSONResponse(
                response.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
            )
        except RauthyTokenRejected:
            return self._answer(401, "MCP_PROVIDER_BEARER_REJECTED")
        except CurrentProjectDenied:
            return self._answer(403, "MCP_CURRENT_PROJECT_REQUIRED")
        except WorkspaceGrantDenied:
            return self._answer(403, "FILES_CURRENT_CEDAR_GRANT_REQUIRED")
        except InvocationAccountDenied:
            return self._answer(403, "MCP_CURRENT_PROJECT_ACCOUNT_REQUIRED")
        except Exception:
            return self._answer(503, "FILES_AUTHORITY_UNAVAILABLE")


def node_workspace_effect_router(
    *,
    module: str,
    platform: PeerClient,
    resources: PeerClient | None,
    resolve_database: Callable[[], PlatformDatabase | None],
    actor_model: type[ActorContext],
    issuers: McpIssuerRegistry,
    signing_key: Ed25519PrivateKey | None,
) -> APIRouter:
    router = APIRouter()
    controller = WorkspaceEffectController(
        module=module,
        platform=platform,
        resources=resources,
        resolve_database=resolve_database,
        actor_model=actor_model,
        issuers=issuers,
        signing_key=signing_key,
    )
    router.add_api_route(
        "/internal/v1/authorization/node-" + module + "-effect",
        controller.authorize,
        methods=["POST"],
        include_in_schema=False,
    )
    return router


def node_files_effect_router(
    *,
    platform: PeerClient,
    resources: PeerClient | None,
    resolve_database: Callable[[], PlatformDatabase | None],
    actor_model: type[ActorContext],
    issuers: McpIssuerRegistry,
    signing_key: Ed25519PrivateKey | None,
) -> APIRouter:
    return node_workspace_effect_router(
        module="files",
        platform=platform,
        resources=resources,
        resolve_database=resolve_database,
        actor_model=actor_model,
        issuers=issuers,
        signing_key=signing_key,
    )
