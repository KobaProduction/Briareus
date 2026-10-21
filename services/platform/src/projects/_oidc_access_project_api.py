"""Platform-owned, private current membership projection for Access/Cedar.

The request's Rauthy identity is a selector only. A separately authenticated
Authorization service peer must attest issuer, sub and requested Project.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._oidc_membership_projection import (
    CurrentRauthyPlatformMembership,
    PlatformOidcMembershipProjection,
    PlatformSubjectLinkUnavailable,
)

_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class AccessMembershipQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    project_uuid: UUID

    @field_validator("project_uuid")
    @classmethod
    def v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Project must be UUIDv4")
        return value


@dataclass(frozen=True, slots=True)
class VerifiedAccessProjectPeer:
    audience: Literal["briareus:platform"]
    consumer: Literal["authorization", "resources"]
    issuer: str
    subject: str
    project_uuid: UUID
    expires_at: datetime


class TrustedAccessProjectAttestor(Protocol):
    async def verify(
        self, request: Request, query: AccessMembershipQuery
    ) -> VerifiedAccessProjectPeer:
        """Must independently authenticate service peer and delegated Rauthy identity."""
        ...


def oidc_access_project_router(
    *,
    projection: PlatformOidcMembershipProjection | None,
    attestor: TrustedAccessProjectAttestor | None,
    resolve_projection: Callable[[], PlatformOidcMembershipProjection | None] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/platform/oidc", tags=["platform-private"])

    def fail(status: int, code: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code}}, status_code=status, headers=_HEADERS)

    @router.post("/actor-context", include_in_schema=False)
    @router.post("/project-member", include_in_schema=False)
    async def project_member(query: AccessMembershipQuery, request: Request) -> JSONResponse:
        source = resolve_projection() if resolve_projection is not None else projection
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
        now = datetime.now(UTC)
        if (
            not isinstance(verified, VerifiedAccessProjectPeer)
            or verified.audience != "briareus:platform"
            or verified.consumer not in {"authorization", "resources"}
            or verified.issuer != query.issuer
            or verified.subject != query.subject
            or verified.project_uuid != query.project_uuid
            or not isinstance(verified.expires_at, datetime)
            or verified.expires_at.tzinfo is None
            or not now < verified.expires_at <= now + timedelta(seconds=30)
        ):
            return fail(403, "PLATFORM_PROJECT_PROOF_DENIED")
        def owner_failure(status, code):
            response=fail(status,code)
            # A denial is an authoritative owner reply too. Without the
            # nonce-bound signature, callers must treat it as unavailable.
            return attestor.sign_reply(request,response) if hasattr(attestor,"sign_reply") else response
        try:
            current = await source.resolve_project(
                issuer=query.issuer, subject=query.subject, project_uuid=query.project_uuid
            )
        except PlatformSubjectLinkUnavailable:
            return owner_failure(503, "PLATFORM_PROJECT_SOURCE_UNAVAILABLE")
        except Exception:
            return owner_failure(503, "PLATFORM_PROJECT_SOURCE_UNAVAILABLE")
        if current is None:
            return owner_failure(403, "PLATFORM_PROJECT_NOT_MEMBER")
        now = datetime.now(UTC)
        if verified.expires_at <= now:
            return owner_failure(503, "PLATFORM_PROJECT_PEER_UNAVAILABLE")
        if (
            not isinstance(current, CurrentRauthyPlatformMembership)
            or current.issuer != query.issuer
            or current.subject != query.subject
            or current.enabled is not True
            or not isinstance(current.user_id, UUID)
            or current.user_id.version != 4
            or current.expires_at.tzinfo is None
            or not now < current.expires_at <= now + timedelta(seconds=30)
        ):
            return owner_failure(503, "PLATFORM_PROJECT_PROOF_INVALID")
        visible = [
            project
            for project in current.projects
            if project.project_id == query.project_uuid and "use_resources" in project.permissions
        ]
        if len(visible) != 1:
            return owner_failure(403, "PLATFORM_PROJECT_NOT_MEMBER")
        response = JSONResponse(
            {
                "issuer": query.issuer,
                "subject": query.subject,
                "actor_uuid": str(current.user_id),
                "project_uuid": str(query.project_uuid),
                "expires_at": min(current.expires_at, verified.expires_at).isoformat(),
                **({"permissions": list(visible[0].permissions), "role": current.role}
                   if request.url.path.endswith("/actor-context") else {}),
                **({"project_owner_kind": visible[0].owner_kind,
                    "project_owner_uuid": str(visible[0].owner_id)}
                   if request.url.path.endswith("/actor-context") and verified.consumer == "resources" else {}),
            },
            headers=_HEADERS,
        )
        if hasattr(attestor, "sign_reply"):
            return attestor.sign_reply(request, response)
        return response

    return router
