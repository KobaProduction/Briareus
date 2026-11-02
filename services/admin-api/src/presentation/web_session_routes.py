"""Retained session HTTP adapters with focused dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from application.panel_views import (
    NavigationItem,
    PanelBootstrap,
)
from application.web_session import LoginWebAdministrator
from application.web_session_contracts import LoginRequest
from fastapi import APIRouter, Request

from presentation.web_admission import SESSION_KEY as _SESSION_KEY
from presentation.web_admission import WebAdmission
from presentation.web_session import WebSessionResponse, web_session_errors


@dataclass(eq=False, repr=False)
class WebSessionController:
    admission: WebAdmission
    login_service: LoginWebAdministrator | None

    def mount(self, router: APIRouter) -> None:
        router.get("/session")(self.session_state)
        router.post("/login")(self.login)
        router.post("/logout")(self.logout)
        router.get("/bootstrap")(self.bootstrap)

    def session_state(self, request: Request) -> WebSessionResponse:
        username = self.admission.authenticated_username(request)
        return WebSessionResponse(authenticated=username is not None, username=username)

    async def login(self, payload: LoginRequest, request: Request) -> WebSessionResponse:
        self.admission.same_origin(request)
        api = self.admission.available(self.login_service)
        with web_session_errors():
            username = await api.execute(payload.username, payload.password)
        request.session[_SESSION_KEY] = username
        return WebSessionResponse(authenticated=True, username=username)

    def logout(self, request: Request) -> WebSessionResponse:
        self.admission.same_origin(request)
        request.session.clear()
        return WebSessionResponse(authenticated=False, username=None)

    def bootstrap(self, request: Request) -> PanelBootstrap:
        self.admission.require_user(request)
        return PanelBootstrap(
            product="MCP Admin API",
            environment="runtime",
            navigation=[
                NavigationItem(id="overview", label="Overview", enabled=True),
                NavigationItem(id="accounts", label="Accounts", enabled=True),
                NavigationItem(id="calls", label="MCP Calls", enabled=True),
                NavigationItem(id="files", label="Files", enabled=True),
                NavigationItem(id="terminal", label="Terminal", enabled=True),
                NavigationItem(id="browser", label="Browser", enabled=True),
                NavigationItem(id="analysis", label="Analysis", enabled=True),
                NavigationItem(id="access", label="Access", enabled=True),
                NavigationItem(id="oauth", label="OAuth Sessions", enabled=True),
                NavigationItem(id="settings", label="Settings", enabled=True),
            ],
        )
