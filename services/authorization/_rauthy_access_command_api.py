"""Rauthy-only private write routes, with one current owner per Access DB.

Neither HTTP fields nor a Panel cookie can create the operator actor.
The attestor must verify independently signed Rauthy actor, Platform role,
private peer and exact operation/Project scope. Without it every path is 503.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from authorization._rauthy_access_commands import (
    AccessRauthyCommandService,
    OpenSessionCommand,
    RequestElevationCommand,
    ResolveElevationCommand,
    RevokeSessionCommand,
)
from authorization.application.idempotency import CommandOutcome
from authorization.application.session_receipts import (
    ElevationResponse,
    OpenSessionResponse,
    RevokeSessionResponse,
)
from common.platform_errors import AccessDenied, Conflict, IdempotencyConflict, InvalidInput


class AccessCommandController:
    def __init__(self, resolve_service: Callable[[], AccessRauthyCommandService | None]) -> None:
        self.resolve_service = resolve_service

    @staticmethod
    async def verified_command(request: Request, operation: UUID) -> None:
        if (
            request.headers.getlist("cookie")
            or request.headers.getlist("origin")
            or request.headers.getlist("authorization") == []
            or len(request.headers.getlist("authorization")) != 1
            or request.headers.getlist("content-type") != ["application/json"]
        ):
            raise HTTPException(401, detail="private authenticated service bearer required")
        if not 1 <= len(await request.body()) <= 32_768:
            raise HTTPException(413, detail="private Access command body too large")
        opaque = str(operation)
        if (
            operation.version != 4
            or request.headers.getlist("operation-uuid") != [opaque]
            or request.headers.getlist("idempotency-key") != [opaque]
        ):
            raise HTTPException(422, detail="canonical signed operation required")

    async def execute(
        self,
        request: Request,
        command: OpenSessionCommand
        | RequestElevationCommand
        | ResolveElevationCommand
        | RevokeSessionCommand,
    ) -> JSONResponse:
        owner = self.resolve_service()
        if owner is None:
            raise HTTPException(503, detail="trusted Access command source unavailable")
        await self.verified_command(request, command.operation_uuid)
        outcome: (
            CommandOutcome[OpenSessionResponse]
            | CommandOutcome[ElevationResponse]
            | CommandOutcome[RevokeSessionResponse]
        )
        try:
            if isinstance(command, OpenSessionCommand):
                outcome = await owner.open_normal(request, command)
            elif isinstance(command, RequestElevationCommand):
                outcome = await owner.request_elevation(request, command)
            elif isinstance(command, ResolveElevationCommand):
                outcome = await owner.resolve_elevation(request, command)
            else:
                outcome = await owner.revoke_session(request, command)
        except AccessDenied:
            raise HTTPException(403, detail="current Project access denied") from None
        except (Conflict, IdempotencyConflict):
            raise HTTPException(409, detail="Access owner revision or replay conflict") from None
        except InvalidInput:
            raise HTTPException(422, detail="invalid signed Access request") from None
        except Exception:
            raise HTTPException(503, detail="Access owner unavailable") from None
        return JSONResponse(
            outcome.body.model_dump(mode="json"),
            status_code=outcome.status,
            headers={"Cache-Control": "no-store"},
        )

    async def open_normal(self, command: OpenSessionCommand, request: Request) -> JSONResponse:
        return await self.execute(request, command)

    async def request_elevation(
        self, command: RequestElevationCommand, request: Request
    ) -> JSONResponse:
        return await self.execute(request, command)

    async def resolve_elevation(
        self, command: ResolveElevationCommand, request: Request
    ) -> JSONResponse:
        return await self.execute(request, command)

    async def revoke_session(self, command: RevokeSessionCommand, request: Request) -> JSONResponse:
        return await self.execute(request, command)


def rauthy_access_command_router(
    *, resolve_service: Callable[[], AccessRauthyCommandService | None]
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["access-private"])
    controller = AccessCommandController(resolve_service)
    router.add_api_route(
        "/sessions/open", controller.open_normal, methods=["POST"], include_in_schema=False
    )
    router.add_api_route(
        "/approvals/request",
        controller.request_elevation,
        methods=["POST"],
        include_in_schema=False,
    )
    router.add_api_route(
        "/approvals/resolve",
        controller.resolve_elevation,
        methods=["POST"],
        include_in_schema=False,
    )
    router.add_api_route(
        "/sessions/revoke", controller.revoke_session, methods=["POST"], include_in_schema=False
    )
    return router
