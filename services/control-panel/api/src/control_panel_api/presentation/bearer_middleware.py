from __future__ import annotations

from briareus_oidc import TokenAccessDenied
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from control_panel_api.application.identity import PanelTokenIdentity
from control_panel_api.presentation.identity import PRINCIPAL_SCOPE_KEY, bearer_token


class PanelBearerMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, identity: PanelTokenIdentity) -> None:
        super().__init__(app)
        self.identity = identity

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith("/admin/api") and request.headers.get("authorization"):
            try:
                token = bearer_token(request.headers["authorization"])
                request.scope[PRINCIPAL_SCOPE_KEY] = await self.identity.verify_async(token)
            except TokenAccessDenied:
                return JSONResponse({"detail": {"code": "access_denied"}}, status_code=403)
            except ValueError:
                return JSONResponse(
                    {"detail": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)
