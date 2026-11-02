# ruff: noqa: B008  # FastAPI Header descriptors are framework-executed defaults
"""Private legacy login HTTP contracts and thin transport controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from common.platform_errors import AuthenticationRateLimited, AuthenticationRequired
from identity.application.private_login import IdentitySourceUnavailable, IssuedIdentityBearer

BEARER_SCHEME = "Bearer"


class PrivateIdentityLoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(min_length=3, max_length=128)
    password: SecretStr = Field(min_length=12, max_length=4096)


class PrivateIdentityLoginResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    access_token: str
    token_type: str = BEARER_SCHEME
    expires_at: datetime


class PrivateLoginSource(Protocol):
    async def login(
        self, *, evidence: object, username: str, password: SecretStr, original_uuid: UUID
    ) -> IssuedIdentityBearer: ...

    async def logout(self, *, evidence: object, bearer: SecretStr) -> None: ...


@dataclass(frozen=True)
class PrivateLoginController:
    source: PrivateLoginSource

    async def login_user(
        self,
        request: Request,
        response: Response,
        body: PrivateIdentityLoginPayload,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=36, max_length=36),
    ) -> PrivateIdentityLoginResult:
        if operation_uuid.version != 4 or idempotency_key != str(operation_uuid):
            raise HTTPException(422, detail="original Identity login key mismatch")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        if request.headers.get("cookie") is not None:
            raise HTTPException(
                401,
                detail="bearer-only Identity login requires verified C2",
                headers={"Cache-Control": "no-store"},
            )
        try:
            issued = await self.source.login(
                evidence=request,
                username=body.username,
                password=body.password,
                original_uuid=operation_uuid,
            )
        except AuthenticationRateLimited:
            raise HTTPException(
                429,
                detail="Identity login rate limit active",
                headers={"Cache-Control": "no-store"},
            ) from None
        except IdentitySourceUnavailable:
            raise HTTPException(
                503,
                detail="current Identity issuer unavailable",
                headers={"Cache-Control": "no-store"},
            ) from None
        except AuthenticationRequired:
            raise HTTPException(
                401,
                detail="invalid Identity credential",
                headers={"Cache-Control": "no-store"},
            ) from None
        # Expose ONLY the properly issued User bearer through a verified,
        # private HTTPS-forwarded response. Never serialize SecretStr blindly.
        return PrivateIdentityLoginResult(
            access_token=issued.token.get_secret_value(),
            expires_at=issued.expires_at,
        )

    async def logout_user(
        self,
        request: Request,
        response: Response,
        operation_uuid: UUID = Header(alias="Operation-UUID"),
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=36, max_length=36),
    ) -> None:
        if operation_uuid.version != 4 or idempotency_key != str(operation_uuid):
            raise HTTPException(422, detail="original Identity logout key mismatch")
        response.headers["Cache-Control"] = "no-store"
        if request.headers.get("cookie") is not None:
            raise HTTPException(
                401,
                detail="bearer-only Identity logout",
                headers={"Cache-Control": "no-store"},
            )
        bearer = request.headers.get("authorization", "")
        if not bearer.startswith("Bearer ") or bearer.count(" ") != 1:
            raise HTTPException(401, detail="current Identity bearer required")
        try:
            await self.source.logout(evidence=request, bearer=SecretStr(bearer[7:]))
        except IdentitySourceUnavailable:
            raise HTTPException(
                503,
                detail="Identity revocation source unavailable",
                headers={"Cache-Control": "no-store"},
            ) from None
        except AuthenticationRequired:
            raise HTTPException(
                401,
                detail="current Identity credential rejected",
                headers={"Cache-Control": "no-store"},
            ) from None


def build_private_login_router(source: PrivateLoginSource) -> APIRouter:
    controller = PrivateLoginController(source)
    router = APIRouter(prefix="/internal/v1/identity", tags=["identity-private-login"])
    router.add_api_route(
        "/login", controller.login_user, methods=["POST"], response_model=PrivateIdentityLoginResult
    )
    router.add_api_route("/logout", controller.logout_user, methods=["POST"], status_code=204)
    return router


def private_http_error_code(status: int) -> str:
    if status == 401:
        return "AUTHENTICATION_REQUIRED"
    if status == 429:
        return "AUTHENTICATION_RATE_LIMITED"
    if status == 403:
        return "INVITATION_REJECTED"
    if status == 422:
        return "INVALID_INPUT"
    return "OWNER_SOURCE_UNAVAILABLE"
