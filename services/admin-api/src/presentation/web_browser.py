"""Retained browser HTTP adapters with focused dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from application.browser_inputs import BrowserPageSelection as BrowserRemoteDebugPayload
from application.browser_inputs import BrowserThemePayload, ViewportPayload
from application.panel_views import (
    BrowserRemoteDebug,
)
from domain.realtime import BrowserDebugIssued
from fastapi import APIRouter, HTTPException, Request
from infrastructure.web import WebAdminClient
from realtime import RealtimeBus
from starlette.responses import Response

from common.browser_contracts import BrowserStatus, ExternalBrowserStatus, PageSummary
from common.browser_remote_debug import (
    BROWSER_REMOTE_DEBUG_TTL_SECONDS,
    issue_browser_remote_debug_token,
)
from presentation.web_admission import WebAdmission
from presentation.web_upstream_errors import web_upstream_errors


@dataclass(frozen=True, slots=True)
class WebBrowserServices:
    web: WebAdminClient
    realtime: RealtimeBus | None


@dataclass(eq=False, repr=False)
class WebBrowserController:
    admission: WebAdmission
    services: WebBrowserServices | None

    def mount(self, router: APIRouter) -> None:
        router.get("/browser/state", response_model_exclude_unset=True)(self.browser_state)
        router.put("/browser/theme", response_model_exclude_unset=True)(self.browser_set_theme)
        router.post("/browser/remote-debug")(self.browser_remote_debug)
        router.get("/browser/devtools/{token}/page/{target_id}/{asset_path:path}")(
            self.browser_devtools_asset
        )
        router.put("/browser/viewport", response_model_exclude_unset=True)(
            self.browser_set_viewport
        )
        router.get("/browser/external/status", response_model_exclude_unset=True)(
            self.browser_external_status
        )
        router.post("/browser/external/connect", response_model_exclude_unset=True)(
            self.browser_external_connect
        )
        router.post("/browser/external/disconnect", response_model_exclude_unset=True)(
            self.browser_external_disconnect
        )
        router.post("/browser/external/reset", response_model_exclude_unset=True)(
            self.browser_external_reset
        )

    async def browser_state(self, request: Request) -> BrowserStatus:
        self.admission.require_user(request)
        with web_upstream_errors():
            return await self.admission.available(self.services).web.status()

    async def browser_set_theme(
        self, payload: BrowserThemePayload, request: Request
    ) -> BrowserStatus:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.web.set_theme(payload.color_scheme)
            if api.realtime is not None:
                await api.realtime.publish(
                    "browser.runtime",
                    "theme.changed",
                    result,
                )
            return result

    async def browser_remote_debug(
        self, payload: BrowserRemoteDebugPayload, request: Request
    ) -> BrowserRemoteDebug:
        api = self.admission.mutation(request, self.services)
        username = self.admission.require_user(request)
        with web_upstream_errors():
            target = await api.web.debug_target(payload.page_id)
        target_id = target.target_id
        if not target_id:
            raise HTTPException(status_code=502, detail="browser target is unavailable")
        token = issue_browser_remote_debug_token(
            self.admission.settings.service_token, username, target_id
        )
        public_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
        if not public_host:
            raise HTTPException(status_code=500, detail="public host is unavailable")
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).casefold()
        secure = forwarded_proto == "https"
        websocket_scheme = "wss" if secure else "ws"
        http_scheme = "https" if secure else "http"
        devtools_parameter = "wss" if secure else "ws"
        remote_path = f"/v1/browser/cdp/{token}/page/{target_id}"
        frontend_path = f"/v1/browser/devtools/{token}/page/{target_id}/devtools/inspector.html"
        response = BrowserRemoteDebug(
            page_id=target.page_id,
            target_id=target_id,
            title=target.title,
            url=target.url,
            expires_in_seconds=BROWSER_REMOTE_DEBUG_TTL_SECONDS,
            websocket_url=f"{websocket_scheme}://{public_host}{remote_path}",
            frontend_url=(
                f"{http_scheme}://{public_host}{frontend_path}?"
                f"{devtools_parameter}={public_host}{remote_path}"
            ),
            devtools_url=(
                "devtools://devtools/bundled/inspector.html?"
                f"{devtools_parameter}={public_host}{remote_path}"
            ),
        )
        if api.realtime is not None:
            await api.realtime.publish(
                "browser.runtime",
                "remote_debug.issued",
                BrowserDebugIssued(page_id=payload.page_id, target_id=target_id),
            )
        return response

    async def browser_devtools_asset(
        self,
        token: str,
        target_id: str,
        asset_path: str,
        request: Request,
    ) -> Response:
        api = self.admission.available(self.services)
        with web_upstream_errors():
            status_code, headers, body = await api.web.devtools_asset(
                token,
                target_id,
                asset_path,
                request.url.query,
            )
        return Response(content=body, status_code=status_code, headers=headers, media_type=None)

    async def browser_set_viewport(self, payload: ViewportPayload, request: Request) -> PageSummary:
        api = self.admission.mutation(request, self.services)
        try:
            result = await api.web.set_viewport(payload.page_id, payload.width, payload.height)
            if api.realtime is not None:
                await api.realtime.publish(
                    "browser.runtime",
                    "viewport.changed",
                    result,
                )
            return result
        except Exception as exc:
            message = str(exc)
            code = (
                404
                if "page" in message.casefold()
                and ("closed" in message.casefold() or "not found" in message.casefold())
                else 502
            )
            raise HTTPException(status_code=code, detail=message) from exc

    async def browser_external_status(self, request: Request) -> ExternalBrowserStatus:
        self.admission.require_user(request)
        with web_upstream_errors():
            return await self.admission.available(self.services).web.external_status()

    async def browser_external_connect(self, request: Request) -> ExternalBrowserStatus:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.web.external_connect()
            if api.realtime is not None:
                await api.realtime.publish(
                    "browser.runtime",
                    "external.connected",
                    result,
                )
            return result

    async def browser_external_disconnect(self, request: Request) -> ExternalBrowserStatus:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.web.external_disconnect()
            if api.realtime is not None:
                await api.realtime.publish(
                    "browser.runtime",
                    "external.disconnected",
                    result,
                )
            return result

    async def browser_external_reset(self, request: Request) -> ExternalBrowserStatus:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.web.external_reset()
            if api.realtime is not None:
                await api.realtime.publish(
                    "browser.runtime",
                    "external.reset",
                    result,
                )
            return result
