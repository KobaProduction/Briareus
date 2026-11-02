"""Private BFF-only composition of current human browser execution authority."""

import asyncio
import base64
import hashlib
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from authorization._rauthy_jwks import RauthyTokenRejected
from authorization.application.human_web import AuthorizeHumanEffect
from authorization.domain.human_web import HumanCall
from authorization.infrastructure.human_web import (
    CurrentHumanBinding,
    CurrentHumanIdentity,
    CurrentHumanResource,
)
from authorization.infrastructure.human_web_policy import CedarHumanPolicy
from authorization.infrastructure.human_web_signer import HumanEffectSigner
from authorization.infrastructure.mcp_issuers import McpIssuerRegistry
from authorization.presentation.runtime_protocol import ActorContext
from node_protocol.module_effects import effect_action, parse_request
from runtime_peer import PeerClient
from runtime_peer.human_web import HumanEffectInput, HumanPermitReceipt


def _human_action(
    module: str, tool: str | None
) -> Literal["web.access", "files.read", "files.write", "terminal.execute", "analysis.import"]:
    action = effect_action(module, tool)
    if action == "web.access":
        return "web.access"
    if action == "files.read":
        return "files.read"
    if action == "files.write":
        return "files.write"
    if action == "terminal.execute":
        return "terminal.execute"
    if action == "analysis.import":
        return "analysis.import"
    raise ValueError("Known human project action required")


def _human_call(command: HumanEffectInput) -> HumanCall:
    raw = base64.b64decode(command.body, validate=True)
    facts = parse_request(command.module, raw)
    return HumanCall(
        command.project_uuid,
        command.request_uuid,
        facts.method,
        facts.tool,
        facts.original_tool,
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(("Bearer " + command.bearer.get_secret_value()).encode()).hexdigest(),
        facts.arguments_digest,
        command.module,
        _human_action(command.module, facts.tool),
    )


async def _validated_call(request: Request) -> tuple[HumanEffectInput, HumanCall]:
    command = HumanEffectInput.model_validate(await request.json())
    if request.url.path.endswith("/human-web-effect") and command.module != "web":
        raise ValueError("The legacy Browser route only accepts Web effects")
    return command, _human_call(command)


def _failure(status: int, code: str) -> JSONResponse:
    return JSONResponse({"code": code}, status_code=status, headers={"Cache-Control": "no-store"})


def human_web_effect_router(
    *,
    platform: PeerClient,
    resources: PeerClient | None,
    actor_model: type[ActorContext],
    issuers: McpIssuerRegistry,
    signing_key: Ed25519PrivateKey | None,
) -> APIRouter:
    router = APIRouter()
    policy = CedarHumanPolicy()

    @router.post("/internal/v1/authorization/human-effect", include_in_schema=False)
    @router.post("/internal/v1/authorization/human-web-effect", include_in_schema=False)
    async def authorize(request: Request) -> JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:control-panel-api":
            return _failure(403, "HUMAN_PANEL_PEER_REQUIRED")
        try:
            command, call = await _validated_call(request)
        except (ValueError, TypeError):
            return _failure(422, "HUMAN_WEB_EFFECT_INVALID")
        keys = issuers.get(command.module)
        if keys is None or resources is None or signing_key is None:
            return _failure(503, "HUMAN_WEB_AUTHORITY_UNAVAILABLE")
        use_case = AuthorizeHumanEffect(
            identities=CurrentHumanIdentity(
                platform, actor_model, keys, command.bearer.get_secret_value(), command.project_uuid
            ),
            bindings=CurrentHumanBinding(resources, command.project_uuid, command.module),
            resources=CurrentHumanResource(resources, command.module),
            policy=policy,
            signer=HumanEffectSigner(signing_key),
        )
        try:
            async with asyncio.timeout(4):
                permit = await use_case.execute(call)
            return JSONResponse(
                HumanPermitReceipt(permit=permit).model_dump(mode="json"),
                headers={"Cache-Control": "no-store"},
            )
        except RauthyTokenRejected:
            return _failure(401, "HUMAN_PROVIDER_BEARER_REJECTED")
        except PermissionError:
            return _failure(403, "HUMAN_WEB_PROJECT_ACCESS_REQUIRED")
        except Exception:
            return _failure(503, "HUMAN_WEB_AUTHORITY_UNAVAILABLE")

    return router
