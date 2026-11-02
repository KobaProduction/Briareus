"""Private Gateway/Hand authorization boundary backed by Access SQL and Cedar.

No user IDs or permissions from request headers/body are trusted. The attestor
is injected ONLY by independently verified Rauthy + service-peer integration.
Without it, the route is mounted but unavailable and cannot grant access.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from authorization._rauthy_jwks import load_authority_json
from authorization._resource_scope import (
    EffectResource,
    HandName,
    resource_key,
    validate_effect_scope,
    validate_project_resource_scope,
)
from authorization.application.decisions import ReadCurrentDecision
from authorization.domain.decisions import AuthorizedCurrentGrant as AuthorizedCurrentGrant
from authorization.domain.decisions import (
    DecisionAuthenticationRequired as DecisionAuthenticationRequired,
)
from authorization.domain.decisions import (
    DecisionAuthorityUnavailable as DecisionAuthorityUnavailable,
)
from authorization.domain.decisions import DecisionEffect, DecisionScope
from authorization.domain.decisions import (
    DecisionScopeDenied as DecisionScopeDenied,
)
from authorization.domain.decisions import VerifiedDecisionCaller as VerifiedDecisionCaller
from authorization.infrastructure.decisions import SqlCurrentDecisionRepository
from authorization.presentation.private_requests import (
    PrivateRequestBodyRejected as PrivateRequestBodyRejected,
)
from authorization.presentation.private_requests import (
    bounded_private_request as bounded_private_request,
)
from common.platform_db import PlatformDatabase

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

_DECISION_AUTH_TIMEOUT_SECONDS = 12.0


class DecisionPermit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    allowed: Literal[True] = True


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_uuid: UUID
    agent_session_uuid: UUID
    action: str = Field(min_length=1, max_length=128)
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    hand: HandName | None = None
    tool: str | None = Field(default=None, min_length=1, max_length=128)
    resource: EffectResource | None = None

    @model_validator(mode="after")
    def effect_boundary(self) -> DecisionCommand:
        if self.action == "mcp.connect":
            if any(value is not None for value in (self.hand, self.tool, self.resource)):
                raise ValueError("Gateway coarse admission cannot claim an effect resource")
        elif self.hand is None or self.tool is None or self.resource is None:
            raise ValueError("Hand effect needs exact hand/tool/resource selection")
        else:
            validate_effect_scope(self.hand, self.tool, self.action, self.resource)
            validate_project_resource_scope(
                project_uuid=self.project_uuid,
                hand=self.hand,
                tool=self.tool,
                resource=self.resource,
            )
        return self

    def effect_key(self) -> str | None:
        if self.resource is None or self.hand is None or self.tool is None:
            return None
        return resource_key(self.hand, self.tool, self.resource)

    def domain_scope(self) -> DecisionScope:
        effect = None
        if self.hand is not None and self.tool is not None and self.resource is not None:
            effect = DecisionEffect(
                self.hand,
                self.tool,
                self.resource.kind,
                self.resource.id,
                resource_key(self.hand, self.tool, self.resource),
            )
        return DecisionScope(
            self.project_uuid,
            self.agent_session_uuid,
            self.action,
            self.expected_grant_revision,
            effect,
        )

    @field_validator("project_uuid", "agent_session_uuid")
    @classmethod
    def canonical_uuid(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Project and AgentSession require UUIDv4")
        return value


class TrustedDecisionAttestor(Protocol):
    async def verify(self, request: Request, command: DecisionCommand) -> VerifiedDecisionCaller | None:
        """Verify bearer/peer and current Project membership; never echo claims."""
        ...


class AuthorizationDecisionReader:
    """Read live Access rows; never query another service's SQL tables."""

    def __init__(self, database: PlatformDatabase) -> None:
        if database.engine.url.database != "briareus_access":
            raise ValueError("Authorization decision reader must use its own Access database")
        self._db = database

    async def current_grant(
        self, command: DecisionCommand, caller: VerifiedDecisionCaller
    ) -> AuthorizedCurrentGrant | None:
        return await ReadCurrentDecision(SqlCurrentDecisionRepository(self._db)).execute(
            command.domain_scope(), caller
        )

    async def permits(self, command: DecisionCommand, caller: VerifiedDecisionCaller) -> bool:
        return await self.current_grant(command, caller) is not None


class AuthorizationDecisionService:
    """Coordinates real peer attestation and database/PARC decision."""

    def __init__(
        self,
        attestor: TrustedDecisionAttestor,
        reader: AuthorizationDecisionReader,
    ) -> None:
        self._attestor = attestor
        self._reader = reader

    async def permits(self, request: Request, command: DecisionCommand) -> bool:
        verified = await self._attestor.verify(request, command)
        if not isinstance(verified, VerifiedDecisionCaller):
            return False
        return await self._reader.permits(command, verified)


class DecisionController:
    def __init__(
        self,
        service: AuthorizationDecisionService | None,
        resolve_service: Callable[[Request], AuthorizationDecisionService | None] | None,
    ) -> None:
        self.service = service
        self.resolve_service = resolve_service

    async def decide(self, request: Request) -> JSONResponse:
        # No FastAPI body-model parameter: it would buffer untrusted bytes
        # BEFORE any identity, peer, length or digest checks.
        try:
            raw, verified_request = await bounded_private_request(request)
            # The transport signs exact bytes; rejecting ambiguous nested
            # JSON ensures no other parser can grant based on a different
            # interpretation of the very same attested body.
            command = DecisionCommand.model_validate(load_authority_json(raw))
        except PrivateRequestBodyRejected as exc:
            raise HTTPException(exc.status_code, detail=exc.reason, headers=_NO_STORE) from None
        except (ValueError, TypeError):
            raise HTTPException(
                422, detail="invalid bounded decision body", headers=_NO_STORE
            ) from None
        active = (
            self.service
            if self.service is not None
            else self.resolve_service(request)
            if self.resolve_service is not None
            else None
        )
        if active is None:
            raise HTTPException(
                503, detail="authorization identity attestation unavailable", headers=_NO_STORE
            )
        try:
            async with asyncio.timeout(_DECISION_AUTH_TIMEOUT_SECONDS):
                allowed = await active.permits(verified_request, command)
        except DecisionAuthenticationRequired:
            raise HTTPException(
                401, detail="authorization caller not authenticated", headers=_NO_STORE
            ) from None
        except DecisionScopeDenied:
            raise HTTPException(403, detail="authorization denied", headers=_NO_STORE) from None
        except DecisionAuthorityUnavailable:
            raise HTTPException(
                503, detail="authorization authority unavailable", headers=_NO_STORE
            ) from None
        except Exception:
            raise HTTPException(
                503, detail="authorization authority unavailable", headers=_NO_STORE
            ) from None
        if not allowed:
            raise HTTPException(403, detail="authorization denied", headers=_NO_STORE)
        return JSONResponse(DecisionPermit().model_dump(), headers=_NO_STORE)


def authorization_decision_router(
    service: AuthorizationDecisionService | None,
    *,
    resolve_service: Callable[[Request], AuthorizationDecisionService | None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["authorization-private"])
    controller = DecisionController(service, resolve_service)
    router.add_api_route("/decide", controller.decide, methods=["POST"], include_in_schema=False)
    return router
