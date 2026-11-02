"""Rauthy/Platform/Access decision for one bounded Files read, without Identity.

This owner does not mint a bearer or an A6 ProjectPermit, choose a filesystem
root, or read file contents. A Files controller must authenticate the private
response and check it both before reading and before releasing bytes, while
retaining its own root/FD incarnation, path confinement and byte limits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from authorization._decision_api import (
    _DECISION_AUTH_TIMEOUT_SECONDS,
    AuthorizationDecisionReader,
    DecisionAuthenticationRequired,
    DecisionAuthorityUnavailable,
    DecisionCommand,
    DecisionScopeDenied,
    PrivateRequestBodyRejected,
    TrustedDecisionAttestor,
    VerifiedDecisionCaller,
    bounded_private_request,
)
from authorization._rauthy_jwks import load_authority_json
from authorization._resource_scope import (
    EffectResource,
    TrustedResourceOwnerPort,
)
from authorization.application.files_read import DecideFilesRead
from authorization.domain.files_read import (
    ReadAuthenticationRequired,
    ReadAuthorityUnavailable,
    ReadScope,
    ReadScopeDenied,
)
from authorization.infrastructure.files_read import CurrentReadAuthorities, SystemClock, read_caller

_PROTOCOL: Literal["files-read-decision-v1"] = "files-read-decision-v1"
_MAX_BYTES = 262_144
_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class FilesReadDecisionCommand(DecisionCommand):
    """Private exact body authenticated by the existing trusted Files peer."""

    protocol: Literal["files-read-decision-v1"]
    operation_uuid: UUID
    phase: Literal["before_read", "after_read"]
    hand: Literal["files"]
    tool: Literal["read_file"]
    action: Literal["files.read"]
    resource: EffectResource
    expected_resource_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    max_bytes: int = Field(strict=True, ge=1, le=_MAX_BYTES)

    @field_validator("operation_uuid")
    @classmethod
    def operation_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Files read operation must be UUIDv4")
        return value

    @model_validator(mode="after")
    def versioned_files_scope(self) -> FilesReadDecisionCommand:
        if not self.resource.id.startswith("project-path-v1:"):
            raise ValueError("Files read requires the owner-resolved Project path selector")
        return self


class FilesReadDecision(BaseModel):
    """Request-bound private result, NOT transferable authorization evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["files-read-decision-v1"] = _PROTOCOL
    allowed: Literal[True] = True
    operation_uuid: UUID
    phase: Literal["before_read", "after_read"]
    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    hand: Literal["files"] = "files"
    tool: Literal["read_file"] = "read_file"
    action: Literal["files.read"] = "files.read"
    resource: EffectResource
    grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    resource_revision: int = Field(strict=True, ge=1, le=2**63 - 1)
    max_bytes: int = Field(strict=True, ge=1, le=_MAX_BYTES)
    checked_at: datetime
    expires_at: datetime


class FilesReadDecisionService:
    """HTTP composition adapter; authority orchestration belongs to the use case."""

    def __init__(
        self,
        *,
        attestor: TrustedDecisionAttestor | None,
        reader: AuthorizationDecisionReader | None,
        resource_owner: TrustedResourceOwnerPort | None,
    ) -> None:
        if attestor is None or reader is None or resource_owner is None:
            raise ValueError("Files read needs identity, Access and current Files owner")
        self._attestor = attestor
        self._reader = reader
        self._owner = resource_owner

    async def decide(
        self, request: Request, command: FilesReadDecisionCommand
    ) -> FilesReadDecision:
        # The trusted adapter still performs signed body/peer/nonce and fresh
        # Platform membership validation for every phase.
        caller = await self._attestor.verify(request, command)
        if not isinstance(caller, VerifiedDecisionCaller):
            raise DecisionAuthenticationRequired("verified Files caller required")
        authorities = CurrentReadAuthorities(command, caller, self._reader, self._owner)
        scope = ReadScope(
            command.project_uuid,
            command.agent_session_uuid,
            command.effect_key(),
            command.expected_grant_revision,
            command.expected_resource_revision,
        )
        try:
            result = await DecideFilesRead(authorities, SystemClock()).execute(
                scope, read_caller(caller)
            )
        except ReadAuthenticationRequired as exc:
            raise DecisionAuthenticationRequired(str(exc)) from exc
        except ReadScopeDenied as exc:
            raise DecisionScopeDenied(str(exc)) from exc
        except ReadAuthorityUnavailable as exc:
            raise DecisionAuthorityUnavailable(str(exc)) from exc
        return FilesReadDecision(
            operation_uuid=command.operation_uuid,
            phase=command.phase,
            actor_uuid=result.actor_uuid,
            project_uuid=command.project_uuid,
            agent_session_uuid=command.agent_session_uuid,
            resource=command.resource,
            grant_revision=result.grant_revision,
            resource_revision=result.resource_revision,
            max_bytes=command.max_bytes,
            checked_at=result.checked_at,
            expires_at=result.expires_at,
        )


def files_read_decision_router(
    *, resolve_service: Callable[[], FilesReadDecisionService | None]
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["access-private"])

    @router.post("/files/read-decision", include_in_schema=False)
    async def read_decision(request: Request) -> JSONResponse:
        try:
            raw, verified_request = await bounded_private_request(request)
            command = FilesReadDecisionCommand.model_validate(load_authority_json(raw))
        except PrivateRequestBodyRejected as exc:
            raise HTTPException(exc.status_code, exc.reason, headers=_HEADERS) from None
        except (ValueError, TypeError):
            raise HTTPException(422, "invalid bounded Files decision", headers=_HEADERS) from None
        active = resolve_service()
        if active is None:
            raise HTTPException(503, "Files read authority unavailable", headers=_HEADERS)
        try:
            async with asyncio.timeout(_DECISION_AUTH_TIMEOUT_SECONDS):
                result = await active.decide(verified_request, command)
        except DecisionAuthenticationRequired:
            raise HTTPException(
                401, "Files read caller not authenticated", headers=_HEADERS
            ) from None
        except DecisionScopeDenied:
            raise HTTPException(403, "Files read denied", headers=_HEADERS) from None
        except Exception:
            # Do not leak provider credentials, path, root, or SQL diagnostics.
            raise HTTPException(503, "Files read authority unavailable", headers=_HEADERS) from None
        return JSONResponse(result.model_dump(mode="json"), headers=_HEADERS)

    return router
