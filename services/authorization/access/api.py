from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel

from common.access_contracts import (
    AccessRequests,
    AccessRequestView,
    AccessSessions,
    AdminResolveRequest,
    AdminSessionOwnerRequest,
    AdminSessionUpdate,
    ExtensionRequest,
    FullAccessRequest,
    ResolvedAccessRequest,
    SessionOpenRequest,
    SessionSnapshot,
    SessionUpdateRequest,
    SessionValidateRequest,
    SurfaceControlBatchUpdate,
    SurfaceControls,
    SurfaceControlUpdate,
    SurfaceControlView,
    UserControls,
    UserControlView,
    ValidationResult,
)
from common.mcp_surfaces import MCP_SURFACE_IDS
from common.settings import AuthorizationServiceSettings

from .control import AccessControl

type _ServiceDependency = Callable[[str | None], Awaitable[None]]


class AccessHealth(BaseModel):
    status: Literal["ok"] = "ok"


def _require(expected: str, authorization: str | None) -> None:
    candidate = f"Bearer {expected}"
    if not authorization or not hmac.compare_digest(authorization, candidate):
        raise HTTPException(status_code=401, detail="unauthorized")


def _register_gateway_sessions(
    app: FastAPI, service: AccessControl, require_gateway: _ServiceDependency
) -> None:
    @app.post("/v1/session/open", dependencies=[Depends(require_gateway)])
    async def open_session(request: SessionOpenRequest) -> SessionSnapshot:
        try:
            session = await service.open_session(request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return session

    @app.post("/v1/session/validate", dependencies=[Depends(require_gateway)])
    async def validate_session(request: SessionValidateRequest) -> ValidationResult:
        return await service.validate(request)

    @app.post("/v1/session/status", dependencies=[Depends(require_gateway)])
    async def status(request: SessionValidateRequest) -> SessionSnapshot:
        session = await service.status(
            context=request,
            surface_id=request.surface_id,
            uid=request.session_uid,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="session_not_found")
        return session

    @app.post("/v1/session/update", dependencies=[Depends(require_gateway)])
    async def update_session(request: SessionUpdateRequest) -> SessionSnapshot:
        try:
            session = await service.update_session(request)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return session


def _register_gateway_requests(
    app: FastAPI, service: AccessControl, require_gateway: _ServiceDependency
) -> None:
    @app.post("/v1/session/request-full-access", dependencies=[Depends(require_gateway)])
    async def request_full_access(request: FullAccessRequest) -> AccessRequestView:
        try:
            pending = await service.request_full_access(request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return pending

    @app.post("/v1/session/request-extension", dependencies=[Depends(require_gateway)])
    async def request_extension(request: ExtensionRequest) -> AccessRequestView:
        try:
            pending = await service.request_extension(request)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return pending


def _register_gateway_session_closure(
    app: FastAPI, service: AccessControl, require_gateway: _ServiceDependency
) -> None:
    @app.post("/v1/session/close", dependencies=[Depends(require_gateway)])
    async def close_session(request: SessionValidateRequest) -> SessionSnapshot:
        try:
            session = await service.close_session(
                context=request,
                surface_id=request.surface_id,
                uid=request.session_uid,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return session

    @app.post("/v1/session/reissue", dependencies=[Depends(require_gateway)])
    async def reissue_session(request: SessionUpdateRequest) -> SessionSnapshot:
        try:
            session = await service.reissue_session(
                context=request,
                surface_id=request.surface_id,
                old_uid=request.session_uid,
                label=request.label,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return session


def _register_admin_sessions(
    app: FastAPI, service: AccessControl, require_admin: _ServiceDependency
) -> None:
    @app.get(
        "/v1/admin/users/{user_id}/sessions",
        dependencies=[Depends(require_admin)],
    )
    async def list_sessions(user_id: str) -> AccessSessions:
        sessions = await service.repository.list_sessions(user_id)
        return AccessSessions(sessions=sessions)

    @app.get(
        "/v1/admin/users/{user_id}/requests",
        dependencies=[Depends(require_admin)],
    )
    async def list_requests(user_id: str) -> AccessRequests:
        requests = await service.repository.list_pending_requests(user_id)
        return AccessRequests(requests=requests)

    @app.post(
        "/v1/admin/requests/{request_id}/resolve",
        dependencies=[Depends(require_admin)],
    )
    async def resolve_request(
        request_id: str,
        request: AdminResolveRequest,
    ) -> ResolvedAccessRequest:
        try:
            resolved, session = await service.resolve_request(request_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ResolvedAccessRequest(request=resolved, session=session)

    @app.patch(
        "/v1/admin/sessions/{session_id}",
        dependencies=[Depends(require_admin)],
    )
    async def admin_update_session(session_id: str, request: AdminSessionUpdate) -> SessionSnapshot:
        try:
            updated = await service.admin_update(session_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return updated

    @app.post(
        "/v1/admin/sessions/{session_id}/revoke",
        status_code=204,
        dependencies=[Depends(require_admin)],
    )
    async def admin_revoke(session_id: str, request: AdminSessionOwnerRequest) -> Response:
        try:
            await service.admin_revoke(session_id, admin_user_id=request.admin_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(status_code=204)


def _register_admin_controls(
    app: FastAPI, service: AccessControl, require_admin: _ServiceDependency
) -> None:
    @app.get(
        "/v1/admin/users/{user_id}/controls",
        dependencies=[Depends(require_admin)],
    )
    async def list_controls(user_id: str) -> SurfaceControls:
        controls: list[SurfaceControlView] = []
        for name, member in MCP_SURFACE_IDS.items():
            controls.append(
                SurfaceControlView(
                    surface=name,
                    surface_id=int(member),
                    mode=await service.get_mode(user_id, int(member)),
                )
            )
        return SurfaceControls(controls=controls)

    @app.put("/v1/admin/controls/batch", dependencies=[Depends(require_admin)])
    async def set_controls_batch(
        request: SurfaceControlBatchUpdate,
    ) -> UserControls:
        resolved = await service.set_modes_batch(
            [(item.user_id, item.surface_id, item.mode) for item in request.items]
        )
        return UserControls(
            controls=[
                UserControlView(user_id=user_id, surface_id=surface_id, mode=mode)
                for user_id, surface_id, mode in resolved
            ]
        )

    @app.put("/v1/admin/control", dependencies=[Depends(require_admin)])
    async def set_control(request: SurfaceControlUpdate) -> UserControlView:
        mode = await service.set_mode(
            user_id=request.user_id,
            surface_id=request.surface_id,
            mode=request.mode,
        )
        return UserControlView(user_id=request.user_id, surface_id=request.surface_id, mode=mode)


def build_access_app(
    service: AccessControl,
    settings: AuthorizationServiceSettings,
) -> FastAPI:
    app = FastAPI(title="Auth Access", docs_url=None, redoc_url=None, openapi_url=None)

    async def require_gateway(
        authorization: str | None = Header(default=None),
    ) -> None:
        _require(settings.gateway_service_token, authorization)

    async def require_admin(
        authorization: str | None = Header(default=None),
    ) -> None:
        _require(settings.admin_service_token, authorization)

    @app.get("/health")
    async def health() -> AccessHealth:
        return AccessHealth()

    _register_gateway_sessions(app, service, require_gateway)
    _register_gateway_requests(app, service, require_gateway)
    _register_gateway_session_closure(app, service, require_gateway)
    _register_admin_sessions(app, service, require_admin)
    _register_admin_controls(app, service, require_admin)
    return app
