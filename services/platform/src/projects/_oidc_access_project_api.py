"""Platform-owned, private current membership projection for Access/Cedar.

The request's Rauthy identity is a selector only. A separately authenticated
Authorization service peer must attest issuer, sub and requested Project.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from projects.application.context import ContextError, CurrentMembership, ReadAccessProjectContext
from projects.domain.context import ContextSelector
from projects.domain.context import VerifiedAccessProjectPeer as VerifiedAccessProjectPeer
from service_runtime._uuid_field_validation import _project_uuid_v4

_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class AccessMembershipQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    project_uuid: UUID

    v4 = field_validator("project_uuid")(staticmethod(_project_uuid_v4))


class TrustedAccessProjectAttestor(Protocol):
    async def verify(
        self, request: Request, query: AccessMembershipQuery
    ) -> VerifiedAccessProjectPeer:
        """Must independently authenticate service peer and delegated Rauthy identity."""
        ...


@runtime_checkable
class ProjectReplySigner(Protocol):
    def sign_reply(self, request: Request, response: JSONResponse) -> JSONResponse: ...


def fail(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=_HEADERS)


def sign_owner_reply(
    attestor: TrustedAccessProjectAttestor,
    request: Request,
    response: JSONResponse,
) -> JSONResponse:
    return (
        attestor.sign_reply(request, response)
        if isinstance(attestor, ProjectReplySigner)
        else response
    )


async def project_response(
    query: AccessMembershipQuery,
    request: Request,
    source: CurrentMembership | None,
    attestor: TrustedAccessProjectAttestor | None,
) -> JSONResponse:
    if source is None or attestor is None:
        return fail(503, "PLATFORM_PROJECT_TRUST_UNAVAILABLE")
    if (
        request.headers.getlist("cookie")
        or request.headers.getlist("origin")
        or len(request.headers.getlist("authorization")) != 1
        or request.headers.getlist("content-type") != ["application/json"]
    ):
        return fail(401, "PLATFORM_PROJECT_PEER_REQUIRED")
    try:
        verified = await attestor.verify(request, query)
    except Exception:
        return fail(503, "PLATFORM_PROJECT_PEER_UNAVAILABLE")
    use_case = ReadAccessProjectContext(source, lambda: datetime.now(UTC))
    try:
        result = await use_case.execute(
            ContextSelector(query.issuer, query.subject, query.project_uuid),
            verified,
            actor_context=request.url.path.endswith("/actor-context"),
        )
    except ContextError as error:
        response = fail(error.status, error.code)
        return sign_owner_reply(attestor, request, response) if error.owner_reply else response
    response = JSONResponse(jsonable_encoder(asdict(result)), headers=_HEADERS)
    return sign_owner_reply(attestor, request, response)


def oidc_access_project_router(
    *,
    projection: CurrentMembership | None,
    attestor: TrustedAccessProjectAttestor | None,
    resolve_projection: Callable[[], CurrentMembership | None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/platform/oidc", tags=["platform-private"])

    @router.post("/actor-context", include_in_schema=False)
    @router.post("/project-member", include_in_schema=False)
    async def project_member(query: AccessMembershipQuery, request: Request) -> JSONResponse:
        source = resolve_projection() if resolve_projection is not None else projection
        return await project_response(query, request, source, attestor)

    return router
