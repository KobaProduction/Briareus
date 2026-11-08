from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from control_panel_api.domain.admin_data.browser import (
    BrowserDebugIssued,
    BrowserRemoteDebug,
    BrowserStatus,
    BrowserStopResult,
    BrowserViewportResult,
    ExternalBrowserAction,
    ExternalBrowserStatus,
)

from .context import WebApiContext
from .contracts import (
    BrowserRemoteDebugPayload,
    BrowserTabPolicyPayload,
    BrowserThemePayload,
    ViewportPayload,
)


class BrowserRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route(
            "/browser/state", self.browser_state, methods=["GET"], response_model_exclude_unset=True
        )
        router.add_api_route(
            "/browser/theme",
            self.browser_set_theme,
            methods=["PUT"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/tabs/policy",
            self.browser_set_tab_policy,
            methods=["PUT"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/remote-debug",
            self.browser_remote_debug,
            methods=["POST"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/viewport",
            self.browser_set_viewport,
            methods=["PUT"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/hard-stop",
            self.browser_hard_stop,
            methods=["POST"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/restart",
            self.browser_restart,
            methods=["POST"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/external/status",
            self.browser_external_status,
            methods=["GET"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/external/connect",
            self.browser_external_connect,
            methods=["POST"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/external/disconnect",
            self.browser_external_disconnect,
            methods=["POST"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/browser/external/reset",
            self.browser_external_reset,
            methods=["POST"],
            response_model_exclude_unset=True,
        )

    async def browser_state(self, request: Request) -> BrowserStatus:
        self.context.require_user(request)
        try:
            return await self.context.available().web.status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_set_theme(
        self, payload: BrowserThemePayload, request: Request
    ) -> BrowserStatus:
        api = self.context.mutation(request)
        try:
            result = await api.web.set_theme(payload.color_scheme)
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "theme.changed", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_remote_debug(
        self, payload: BrowserRemoteDebugPayload, request: Request
    ) -> BrowserRemoteDebug:
        api = self.context.mutation(request)
        try:
            target = await api.web.debug_target(payload.page_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        target_id = target.target_id
        if not target_id:
            raise HTTPException(status_code=502, detail="browser target is unavailable")
        response = BrowserRemoteDebug(
            page_id=target.page_id,
            target_id=target.target_id,
            title=target.title,
            url=target.url,
            websocket_path=f"/api/browser/cdp/page/{target_id}",
            protocol="briareus.v1",
        )
        if api.realtime is not None:
            await api.realtime.publish(
                "browser.runtime",
                "remote_debug.issued",
                BrowserDebugIssued(page_id=payload.page_id, target_id=target_id),
            )
        return response

    async def browser_set_tab_policy(
        self, payload: BrowserTabPolicyPayload, request: Request
    ) -> BrowserStatus:
        api = self.context.mutation(request)
        try:
            result = await api.web.set_tab_policy(
                max_tabs=payload.max_tabs,
                idle_close_enabled=payload.idle_close_enabled,
                idle_timeout_seconds=payload.idle_timeout_seconds,
            )
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "tabs.policy.changed", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_set_viewport(
        self, payload: ViewportPayload, request: Request
    ) -> BrowserViewportResult:
        api = self.context.mutation(request)
        try:
            result = await api.web.set_viewport(payload.page_id, payload.width, payload.height)
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "viewport.changed", result)
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

    async def browser_hard_stop(self, request: Request) -> BrowserStopResult:
        service = self.context.mutation(request)
        try:
            result = await service.web.hard_stop()
            await self.context.publish_management_event(
                service, "browser.runtime.hard_stopped", result
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_restart(self, request: Request) -> BrowserStatus:
        service = self.context.mutation(request)
        try:
            result = await service.web.restart()
            await self.context.publish_management_event(
                service, "browser.runtime.restarted", result
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_external_status(self, request: Request) -> ExternalBrowserStatus:
        self.context.require_user(request)
        try:
            return await self.context.available().web.external_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_external_connect(self, request: Request) -> ExternalBrowserAction:
        api = self.context.mutation(request)
        try:
            result = await api.web.external_connect()
            if api.realtime is not None:
                event = (
                    "external.connected"
                    if result.ok is True
                    else "external.connect_failed"
                    if result.ok is False
                    else "external.connecting"
                )
                await api.realtime.publish("browser.runtime", event, result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_external_disconnect(self, request: Request) -> ExternalBrowserAction:
        api = self.context.mutation(request)
        try:
            result = await api.web.external_disconnect()
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "external.disconnected", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_external_reset(self, request: Request) -> ExternalBrowserAction:
        api = self.context.mutation(request)
        try:
            result = await api.web.external_reset()
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "external.reset", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
