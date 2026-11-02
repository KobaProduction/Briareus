from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.responses import RedirectResponse
from starlette.websockets import WebSocket

from common.identity_provider import IdentityProviderError
from control_panel_api.application.identity import IdentityFlowError, PanelIdentityService
from control_panel_api.domain.identity import (
    PANEL_LOGIN_KEY,
    PANEL_SESSION_KEY,
    PanelIdentitySession,
)


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authenticated: bool
    username: str | None = None
    subject: str | None = None
    csrf_token: str = ""
    logout_url: str = ""


def request_session(
    request: Request, identity: PanelIdentityService
) -> PanelIdentitySession | None:
    identifier = request.session.get(PANEL_SESSION_KEY)
    return identity.current(identifier) if isinstance(identifier, str) else None


def require_origin(request: Request, public_origin: str) -> None:
    if request.headers.get("origin", "") != public_origin:
        raise HTTPException(status_code=403, detail="origin rejected")


async def websocket_session(
    websocket: WebSocket,
    identity: PanelIdentityService,
    public_origin: str,
) -> PanelIdentitySession | None:
    if websocket.headers.get("origin", "") != public_origin:
        await websocket.close(code=4403)
        return None
    cookie = websocket.scope.get("session")
    identifier = cookie.get(PANEL_SESSION_KEY) if isinstance(cookie, dict) else None
    session = identity.current(identifier) if isinstance(identifier, str) else None
    if session is None:
        await websocket.close(code=4401)
    return session


def require_mutation(
    request: Request, identity: PanelIdentityService, public_origin: str
) -> PanelIdentitySession:
    session = request_session(request, identity)
    if session is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    require_origin(request, public_origin)
    try:
        identity.require_csrf(session, request.headers.get("x-csrf-token", ""))
    except IdentityFlowError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    return session


def build_identity_router(identity: PanelIdentityService, public_origin: str) -> APIRouter:
    router = APIRouter(prefix="/admin/api")

    @router.get("/session")
    def session_state(request: Request) -> SessionState:
        session = request_session(request, identity)
        if session is None:
            request.session.pop(PANEL_SESSION_KEY, None)
            return SessionState(authenticated=False)
        return SessionState(
            authenticated=True,
            username=session.grant.display_name,
            subject=session.grant.subject,
            csrf_token=session.csrf_token,
        )

    @router.get("/auth/login")
    async def begin_login(request: Request) -> RedirectResponse:
        try:
            transaction = await asyncio.to_thread(identity.begin)
        except IdentityProviderError:
            raise HTTPException(status_code=503, detail="identity provider unavailable") from None
        request.session[PANEL_LOGIN_KEY] = transaction.state
        return RedirectResponse(
            transaction.url, status_code=303, headers={"Cache-Control": "no-store"}
        )

    @router.get("/auth/callback")
    async def complete_login(request: Request, state: str = "", code: str = "") -> RedirectResponse:
        cookie_state = request.session.pop(PANEL_LOGIN_KEY, "")
        if not isinstance(cookie_state, str) or not code:
            raise HTTPException(status_code=400, detail="invalid identity callback")
        try:
            session = await asyncio.to_thread(
                identity.complete,
                cookie_state=cookie_state,
                state=state,
                code=code,
            )
        except (IdentityFlowError, IdentityProviderError):
            raise HTTPException(
                status_code=401, detail="identity login could not be verified"
            ) from None
        previous = request.session.get(PANEL_SESSION_KEY)
        if isinstance(previous, str):
            identity.repository.delete_session(previous)
        request.session.clear()
        request.session[PANEL_SESSION_KEY] = session.identifier
        return RedirectResponse(
            public_origin + "/admin/", status_code=303, headers={"Cache-Control": "no-store"}
        )

    @router.post("/logout")
    async def logout(request: Request) -> SessionState:
        session = require_mutation(request, identity, public_origin)
        request.session.clear()
        destination = await asyncio.to_thread(identity.logout, session)
        return SessionState(authenticated=False, logout_url=destination)

    return router
