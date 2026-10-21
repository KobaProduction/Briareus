"""Rauthy + Platform + live Cedar connection admission for Gateway only."""
import asyncio
import os
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from authorization._decision_api import DecisionCommand, AuthorizationDecisionReader, VerifiedDecisionCaller
from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from authorization._rauthy_jwks import RauthyKeysUnavailable, RauthyTokenRejected


class AdmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bearer: SecretStr = Field(min_length=40, max_length=8192)
    module: Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"]
    decision: DecisionCommand


class CurrentProjectDenied(ValueError):
    pass


async def current_identity(*, platform, actor_model, keys, bearer, project_uuid):
    verifier = await keys.get_verifier()
    signed = verifier.verify_access_token(bearer)
    status, context = await platform.call("/internal/v1/platform/oidc/actor-context", {
        "issuer": signed.issuer, "subject": signed.subject, "project_uuid": str(project_uuid)})
    if status==403:
        raise CurrentProjectDenied("Current project access denied")
    if status != 200:
        raise ValueError("Current project identity unavailable")
    actor = actor_model.model_validate(context)
    now = datetime.now(UTC)
    if (actor.issuer != signed.issuer or actor.subject != signed.subject
        or actor.project_uuid != project_uuid or actor.actor_uuid.version != 4
        or "use_resources" not in actor.permissions or actor.expires_at.tzinfo is None
        or not now < actor.expires_at <= now + timedelta(seconds=30) or signed.expires_at <= now):
        raise ValueError("Current project identity unavailable")
    return actor, signed


def configured_issuers():
    raw = os.environ.get("MCP_RESOURCE_AUDIENCES", "{}")
    audiences = json.loads(raw)
    from node_protocol.module_effects import MODULES
    if (not isinstance(audiences, dict) or len(audiences) > len(MODULES)
        or set(audiences) - MODULES
        or any(not isinstance(value, str) or not value.startswith("https://") for value in audiences.values())):
        raise ValueError("Explicit MCP resource audience map required")
    if not audiences:
        return {}
    issuer = urlsplit(os.environ["MCP_OIDC_ISSUER"])
    local_fetch = None
    if os.environ.get("MCP_LOCAL_TLS_DIAL"):
        if (os.environ.get("BRIAREUS_LOCAL_TESTING") != "1"
            or os.environ["MCP_OIDC_ISSUER"] != "https://127.0.0.1/auth/v1/"
            or os.environ["MCP_LOCAL_TLS_DIAL"] != "local-tls"):
            raise ValueError("Local HTTPS dial override is restricted to the local Compose issuer")
        from authorization._local_rauthy_keys import fetch_local_issuer
        local_fetch = fetch_local_issuer
    for module, audience in audiences.items():
        parsed = urlsplit(audience)
        if (parsed.scheme != "https" or parsed.netloc != issuer.netloc
            or parsed.path != f"/hands/{module}/mcp" or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
            raise ValueError("Exact same-origin MCP resource audience required")
    return {module: TrustedRauthyIssuerKeys(issuer=os.environ["MCP_OIDC_ISSUER"],
        resource_audience=audience, oauth_client_id=os.environ["MCP_OAUTH_CLIENT_ID"], json_fetch=local_fetch)
        for module, audience in audiences.items()}


def mcp_admission_router(*, platform, resolve_database, actor_model, issuers):
    router = APIRouter()

    def answer(status, code):
        return JSONResponse({"code": code}, status_code=status, headers={"Cache-Control": "no-store"})

    @router.post("/internal/v1/authorization/mcp-admission", include_in_schema=False)
    async def admission(request: Request):
        if request.scope.get("briareus.service_peer") != "briareus:gateway":
            return answer(403, "GATEWAY_PEER_REQUIRED")
        # SignedOwnerApp has already bounded and authenticated exact bytes.
        # Parse manually to avoid validation responses echoing bearer input.
        try:
            command = AdmissionInput.model_validate(await request.json())
            if command.decision.action != "mcp.connect":
                raise ValueError("Coarse connection admission only")
        except (ValueError, TypeError):
            return answer(422, "MCP_ADMISSION_INVALID")
        database = resolve_database()
        keys = issuers.get(command.module)
        if database is None or keys is None:
            return answer(503, "MCP_AUTHORITY_UNAVAILABLE")
        try:
            async with asyncio.timeout(4):
                verifier = await keys.get_verifier()
                signed = verifier.verify_access_token(command.bearer.get_secret_value())
                status, context = await platform.call("/internal/v1/platform/oidc/actor-context", {
                    "issuer": signed.issuer, "subject": signed.subject,
                    "project_uuid": str(command.decision.project_uuid)})
                if status != 200:
                    return answer(403 if status == 403 else 503, "MCP_CURRENT_PROJECT_REQUIRED")
                actor = actor_model.model_validate(context)
                now = datetime.now(UTC)
                if (actor.issuer != signed.issuer or actor.subject != signed.subject
                    or actor.project_uuid != command.decision.project_uuid or actor.actor_uuid.version != 4
                    or "use_resources" not in actor.permissions or actor.expires_at.tzinfo is None
                    or not now < actor.expires_at <= now + timedelta(seconds=30)
                    or signed.expires_at <= now):
                    return answer(403, "MCP_CURRENT_PROJECT_REQUIRED")
                caller = VerifiedDecisionCaller(actor_uuid=actor.actor_uuid,
                    project_uuid=command.decision.project_uuid,
                    agent_session_uuid=command.decision.agent_session_uuid,
                    consumer="gateway", authority="rauthy", verified_peer_audience="briareus:access",
                    proof_expires_at=min(actor.expires_at, signed.expires_at), attested_effect_key=None)
                current = await AuthorizationDecisionReader(database).current_grant(command.decision, caller)
                if current is None:
                    return answer(403, "MCP_CURRENT_CEDAR_GRANT_REQUIRED")
                if current.expires_at <= datetime.now(UTC):
                    return answer(403, "MCP_AUTHORITY_EXPIRED")
                return JSONResponse({"allowed": True}, headers={"Cache-Control": "no-store"})
        except RauthyTokenRejected:
            return answer(401, "MCP_PROVIDER_BEARER_REJECTED")
        except (RauthyKeysUnavailable, TimeoutError, ValueError, OSError):
            return answer(503, "MCP_AUTHORITY_UNAVAILABLE")
        except Exception:
            # Database and authenticated peer failures do not carry upstream
            # exception text, tokens or SQL details onto the transport.
            return answer(503, "MCP_AUTHORITY_UNAVAILABLE")

    return router
