"""Shared HTTP admission without coupling route families to all service clients."""

from application.web_session import CurrentWebAdministrator
from domain.web_session import WebUser
from fastapi import HTTPException, Request, status
from origin import origin_allowed

from common.settings import AdminApiSettings
from presentation.web_session import web_session_errors

SESSION_KEY = "admin_api_session"


class WebAdmission:
    def __init__(
        self,
        settings: AdminApiSettings,
        current_user: CurrentWebAdministrator,
        *,
        services_available: bool,
    ) -> None:
        self.settings = settings
        self._current_user = current_user
        self._services_available = services_available

    def authenticated_username(self, request: Request) -> str | None:
        username = request.session.get(SESSION_KEY)
        if not isinstance(username, str) or not username:
            return None
        return username

    def require_user(self, request: Request) -> str:
        username = self.authenticated_username(request)
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")
        return username

    def same_origin(self, request: Request) -> None:
        origin = request.headers.get("origin", "")
        if not origin:
            return
        public_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if not origin_allowed(origin, public_host, self.settings.admin_ui_origin):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin rejected")

    def available[Services](self, services: Services | None) -> Services:
        if services is None:
            raise HTTPException(status_code=503, detail="admin API services unavailable")
        return services

    def mutation[Services](self, request: Request, services: Services | None) -> Services:
        self.require_user(request)
        self.same_origin(request)
        return self.available(services)

    async def local_user(self, request: Request) -> WebUser:
        username = self.require_user(request)
        if not self._services_available:
            raise HTTPException(status_code=503, detail="admin API services unavailable")
        with web_session_errors():
            return await self._current_user.execute(username)
