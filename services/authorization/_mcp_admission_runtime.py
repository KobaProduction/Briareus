"""Gateway-only HTTP composition for real Rauthy/Platform/Cedar admission."""

import asyncio
from collections.abc import Callable
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from authorization._decision_api import AuthorizationDecisionReader, DecisionCommand
from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from authorization._rauthy_jwks import RauthyTokenRejected
from authorization.application.mcp_admission import AdmitMcpConnection
from authorization.domain.mcp_identity import CurrentProjectDenied as CurrentProjectDenied
from authorization.domain.mcp_identity import (
    InvalidCurrentIdentity,
    McpAuthorityExpired,
    McpGrantDenied,
    ProjectContextLookupFailed,
)
from authorization.infrastructure.mcp_admission import SqlMcpAdmissionGrant
from authorization.infrastructure.mcp_identity import (
    CurrentIdentityResolution,
    PeerWorkspaceIdentity,
    resolve_current_identity,
)
from authorization.infrastructure.mcp_issuers import McpIssuerRegistry
from authorization.infrastructure.mcp_issuers import configured_issuers as configured_issuers
from authorization.presentation.runtime_protocol import ActorContext
from common.platform_db import PlatformDatabase
from runtime_peer import PeerClient


class AdmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bearer: SecretStr = Field(min_length=40, max_length=8192)
    module: Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"]
    decision: DecisionCommand


async def current_identity(
    *,
    platform: PeerClient,
    actor_model: type[ActorContext],
    keys: TrustedRauthyIssuerKeys,
    bearer: str,
    project_uuid: UUID,
) -> CurrentIdentityResolution:
    try:
        return await resolve_current_identity(
            platform=platform,
            actor_model=actor_model,
            keys=keys,
            bearer=bearer,
            project_uuid=project_uuid,
        )
    except ProjectContextLookupFailed as exc:
        if exc.status == 403:
            raise CurrentProjectDenied("Current project access denied") from exc
        raise


def _answer(status: int, code: str) -> JSONResponse:
    return JSONResponse({"code": code}, status_code=status, headers={"Cache-Control": "no-store"})


class McpAdmissionController:
    def __init__(
        self,
        *,
        platform: PeerClient,
        resolve_database: Callable[[], PlatformDatabase | None],
        actor_model: type[ActorContext],
        issuers: McpIssuerRegistry,
    ) -> None:
        self.platform = platform
        self.resolve_database = resolve_database
        self.actor_model = actor_model
        self.issuers = issuers

    async def admission(self, request: Request) -> JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:gateway":
            return _answer(403, "GATEWAY_PEER_REQUIRED")
        try:
            command = AdmissionInput.model_validate(await request.json())
            if command.decision.action != "mcp.connect":
                raise ValueError("Coarse connection admission only")
        except (ValueError, TypeError):
            return _answer(422, "MCP_ADMISSION_INVALID")
        database, keys = self.resolve_database(), self.issuers.get(command.module)
        if database is None or keys is None:
            return _answer(503, "MCP_AUTHORITY_UNAVAILABLE")
        try:
            identities = PeerWorkspaceIdentity(
                platform=self.platform,
                actor_model=self.actor_model,
                keys=keys,
                bearer=command.bearer.get_secret_value(),
                project_uuid=command.decision.project_uuid,
                resolver=resolve_current_identity,
            )
            use_case = AdmitMcpConnection(
                identities,
                SqlMcpAdmissionGrant(AuthorizationDecisionReader(database), command.decision),
            )
        except Exception:
            return _answer(503, "MCP_AUTHORITY_UNAVAILABLE")
        return await self._admit(use_case)

    @staticmethod
    async def _admit(use_case: AdmitMcpConnection) -> JSONResponse:
        try:
            async with asyncio.timeout(4):
                await use_case.execute()
                return JSONResponse({"allowed": True}, headers={"Cache-Control": "no-store"})
        except RauthyTokenRejected:
            return _answer(401, "MCP_PROVIDER_BEARER_REJECTED")
        except ProjectContextLookupFailed as exc:
            return _answer(403 if exc.status == 403 else 503, "MCP_CURRENT_PROJECT_REQUIRED")
        except InvalidCurrentIdentity:
            return _answer(403, "MCP_CURRENT_PROJECT_REQUIRED")
        except McpGrantDenied:
            return _answer(403, "MCP_CURRENT_CEDAR_GRANT_REQUIRED")
        except McpAuthorityExpired:
            return _answer(403, "MCP_AUTHORITY_EXPIRED")
        except Exception:
            return _answer(503, "MCP_AUTHORITY_UNAVAILABLE")


def mcp_admission_router(
    *,
    platform: PeerClient,
    resolve_database: Callable[[], PlatformDatabase | None],
    actor_model: type[ActorContext],
    issuers: McpIssuerRegistry,
) -> APIRouter:
    router = APIRouter()
    controller = McpAdmissionController(
        platform=platform,
        resolve_database=resolve_database,
        actor_model=actor_model,
        issuers=issuers,
    )
    router.add_api_route(
        "/internal/v1/authorization/mcp-admission",
        controller.admission,
        methods=["POST"],
        include_in_schema=False,
    )
    return router
