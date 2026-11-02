"""Private HTTP composition for current Access-owned session/approval reads."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from authorization._decision_api import (
    DecisionAuthenticationRequired,
    DecisionAuthorityUnavailable,
    DecisionScopeDenied,
)
from authorization.application.access_inputs import (
    ApprovalListCommand as ApprovalListCommand,
)
from authorization.application.access_inputs import (
    SessionGetCommand as SessionGetCommand,
)
from authorization.application.session_reads import ReadProjectSessions, SessionReadQuery
from authorization.domain.session_reads import (
    ApprovalReadEntry,
    SessionReadDenied,
    SessionReadEntry,
    SessionReadUnavailable,
)
from authorization.domain.session_reads import VerifiedApprovalActor as VerifiedApprovalActor
from authorization.infrastructure.session_reads import SqlSessionReadRepository
from authorization.presentation.session_reads import approval_response, session_response
from common.platform_db import PlatformDatabase


class TrustedApprovalListAttestor(Protocol):
    async def verify(
        self, request: Request, command: ApprovalListCommand
    ) -> VerifiedApprovalActor: ...


class RequestApprovalAuthority:
    def __init__(
        self,
        request: Request,
        command: ApprovalListCommand,
        attestor: TrustedApprovalListAttestor,
    ) -> None:
        self.request = request
        self.command = command
        self.attestor = attestor

    async def verify(self) -> VerifiedApprovalActor:
        if len(self.request.headers.getlist("authorization")) != 1 or self.request.headers.get(
            "cookie"
        ):
            raise DecisionAuthenticationRequired
        try:
            actor = await self.attestor.verify(self.request, self.command)
        except (DecisionAuthenticationRequired, DecisionAuthorityUnavailable, DecisionScopeDenied):
            raise
        except Exception:
            raise DecisionAuthorityUnavailable from None
        if not isinstance(actor, VerifiedApprovalActor):
            raise DecisionScopeDenied
        return actor


@contextmanager
def _read_errors() -> Iterator[None]:
    try:
        yield
    except SessionReadDenied:
        raise DecisionScopeDenied from None
    except SessionReadUnavailable:
        raise DecisionAuthorityUnavailable from None


class ApprovalListReader:
    def __init__(
        self, *, database: PlatformDatabase, attestor: TrustedApprovalListAttestor
    ) -> None:
        if database.engine.url.database != "briareus_access" or attestor is None:
            raise ValueError("approval list must read only trusted Access owner DB")
        self._db = database
        self._attestor = attestor

    def _application(self, request: Request, command: ApprovalListCommand) -> ReadProjectSessions:
        return ReadProjectSessions(
            RequestApprovalAuthority(request, command, self._attestor),
            SqlSessionReadRepository(self._db),
        )

    async def list(
        self, request: Request, command: ApprovalListCommand
    ) -> tuple[ApprovalReadEntry, ...]:
        with _read_errors():
            return await self._application(request, command).approvals(
                SessionReadQuery(command.project_uuid, command.limit),
            )

    async def list_sessions(
        self, request: Request, command: ApprovalListCommand
    ) -> tuple[SessionReadEntry, ...]:
        with _read_errors():
            return await self._application(request, command).sessions(
                SessionReadQuery(
                    command.project_uuid,
                    command.limit,
                    command.session_uuid if isinstance(command, SessionGetCommand) else None,
                )
            )


@contextmanager
def _http_read_errors(kind: str) -> Iterator[None]:
    try:
        yield
    except DecisionAuthenticationRequired:
        raise HTTPException(401, detail=f"{kind} caller not authenticated") from None
    except DecisionScopeDenied:
        raise HTTPException(403, detail=f"{kind} Project scope denied") from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, detail=f"{kind} authority unavailable") from None


class ApprovalReadController:
    def __init__(self, resolve_reader: Callable[[], ApprovalListReader | None]) -> None:
        self.resolve_reader = resolve_reader

    def _reader(self, kind: str) -> ApprovalListReader:
        active = self.resolve_reader()
        if active is None:
            raise HTTPException(503, detail=f"{kind} authority unavailable")
        return active

    async def list_approvals(self, command: ApprovalListCommand, request: Request) -> JSONResponse:
        with _http_read_errors("approval"):
            entries = await self._reader("approval").list(request, command)
            return JSONResponse(
                {"items": [approval_response(entry).model_dump(mode="json") for entry in entries]},
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )

    async def list_sessions(self, command: ApprovalListCommand, request: Request) -> JSONResponse:
        with _http_read_errors("session read"):
            entries = await self._reader("session read").list_sessions(request, command)
            return JSONResponse(
                {"items": [session_response(entry).model_dump(mode="json") for entry in entries]},
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )

    async def get_session(self, command: SessionGetCommand, request: Request) -> JSONResponse:
        with _http_read_errors("session detail"):
            entries = await self._reader("session detail").list_sessions(request, command)
            if len(entries) > 1:
                raise HTTPException(503, detail="session detail owner inconsistent")
            if not entries:
                raise HTTPException(
                    404,
                    detail="AgentSession not found",
                    headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
                )
            if entries[0].session_uuid != command.session_uuid:
                raise HTTPException(503, detail="session detail owner selector mismatch")
            return JSONResponse(
                {"item": session_response(entries[0]).model_dump(mode="json")},
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )


def private_approval_list_router(
    *, resolve_reader: Callable[[], ApprovalListReader | None]
) -> APIRouter:
    router = APIRouter(prefix="/internal/v1/authorization", tags=["access-private"])
    controller = ApprovalReadController(resolve_reader)
    router.add_api_route(
        "/approvals/list", controller.list_approvals, methods=["POST"], include_in_schema=False
    )
    router.add_api_route(
        "/sessions/list", controller.list_sessions, methods=["POST"], include_in_schema=False
    )
    router.add_api_route(
        "/sessions/get", controller.get_session, methods=["POST"], include_in_schema=False
    )
    return router
