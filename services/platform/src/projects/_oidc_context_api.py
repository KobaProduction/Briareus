"""Private current Platform projection, never a public OAuth/login endpoint.

Peer evidence is independently verified by an explicitly injected transport
adapter; a client-supplied issuer/subject does NOT authenticate a person or
authorize SQL visibility. Default release exposes only unavailable status.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from projects.application.context import ContextError, CurrentMembership, ReadPanelContext
from projects.domain.context import ContextSelector
from projects.domain.context import VerifiedPanelContextPeer as VerifiedPanelContextPeer
from service_runtime._http_errors import error_response as denied

from ._oidc_membership_projection import (
    CurrentRauthyPlatformMembership,
)

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class PlatformContextQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    project_uuid: UUID | None = None

    @field_validator("project_uuid")
    @classmethod
    def v4(cls, value: UUID | None) -> UUID | None:
        if value is not None and value.version != 4:
            raise ValueError("Project must be UUIDv4")
        return value


class TrustedPanelContextAttestor(Protocol):
    async def verify(
        self, request: Request, query: PlatformContextQuery
    ) -> VerifiedPanelContextPeer:
        """Attest authenticated service transport AND delegated subject."""
        ...


class PanelContextNotAuthenticated(Exception):
    """No valid service/subject attestation was presented."""


class PanelContextOwnerUnavailable(Exception):
    """Trusted peer or Platform SQL authority cannot produce a fresh context."""


def context_response(result: CurrentRauthyPlatformMembership) -> JSONResponse:
    return JSONResponse(
        {
            "issuer": result.issuer,
            "subject": result.subject,
            "user_uuid": str(result.user_id),
            "enabled": True,
            "role": result.role,
            "directory_paged": result.directory_paged,
            "name": result.name,
            "email": result.email,
            "expires_at": result.expires_at.isoformat(),
            "teams": [
                {
                    "team_uuid": str(team.team_id),
                    "owner": team.owner,
                    "name": team.name,
                    "member": team.member,
                }
                for team in result.teams
            ],
            "projects": [
                {
                    "project_uuid": str(project.project_id),
                    "name": project.name,
                    "owner_kind": project.owner_kind,
                    "owner_uuid": str(project.owner_id),
                    "permissions": list(project.permissions),
                }
                for project in result.projects
            ],
        },
        headers=_NO_STORE,
    )


async def current_response(
    query: PlatformContextQuery,
    request: Request,
    source: CurrentMembership | None,
    attestor: TrustedPanelContextAttestor | None,
) -> JSONResponse:
    if source is None or attestor is None:
        return denied(503, "PLATFORM_TRUST_NOT_CONFIGURED")
    if request.headers.getlist("cookie") or len(request.headers.getlist("authorization")) != 1:
        return denied(401, "PLATFORM_SERVICE_PROOF_REQUIRED")
    try:
        verified = await attestor.verify(request, query)
    except PanelContextNotAuthenticated:
        return denied(401, "PLATFORM_SERVICE_PROOF_REQUIRED")
    except Exception:
        return denied(503, "PLATFORM_TRUST_UNAVAILABLE")
    use_case = ReadPanelContext(source, lambda: datetime.now(UTC))
    try:
        result = await use_case.execute(
            ContextSelector(query.issuer, query.subject, query.project_uuid), verified
        )
    except ContextError as error:
        return denied(error.status, error.code)
    return context_response(result)


def current_platform_context_router(
    *,
    projection: CurrentMembership | None,
    attestor: TrustedPanelContextAttestor | None,
    resolve_projection: Callable[[], CurrentMembership | None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/platform/oidc", tags=["platform-private"])

    @router.post("/current", include_in_schema=False)
    async def current(query: PlatformContextQuery, request: Request) -> JSONResponse:
        source = resolve_projection() if resolve_projection is not None else projection
        return await current_response(query, request, source, attestor)

    return router
