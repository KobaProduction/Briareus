from __future__ import annotations

from briareus_json_values import JsonObject
from fastapi import APIRouter, HTTPException, Request

from .context import WebApiContext
from .contracts import (
    BrowserRemoteDebugPayload,
    BrowserThemePayload,
    ViewportPayload,
)


class BrowserRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/browser/state", self.browser_state, methods=["GET"])
        router.add_api_route("/browser/theme", self.browser_set_theme, methods=["PUT"])
        router.add_api_route("/browser/remote-debug", self.browser_remote_debug, methods=["POST"])
        router.add_api_route("/browser/viewport", self.browser_set_viewport, methods=["PUT"])
        router.add_api_route("/browser/hard-stop", self.browser_hard_stop, methods=["POST"])
        router.add_api_route("/browser/restart", self.browser_restart, methods=["POST"])
        router.add_api_route(
            "/browser/external/status", self.browser_external_status, methods=["GET"]
        )
        router.add_api_route(
            "/browser/external/connect", self.browser_external_connect, methods=["POST"]
        )
        router.add_api_route(
            "/browser/external/disconnect", self.browser_external_disconnect, methods=["POST"]
        )
        router.add_api_route(
            "/browser/external/reset", self.browser_external_reset, methods=["POST"]
        )

    async def browser_state(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        try:
            return await self.context.available().web.status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_set_theme(self, payload: BrowserThemePayload, request: Request) -> JsonObject:
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
    ) -> JsonObject:
        api = self.context.mutation(request)
        try:
            target = await api.web.debug_target(payload.page_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        target_id = str(target.get("target_id") or "")
        if not target_id:
            raise HTTPException(status_code=502, detail="browser target is unavailable")
        response: JsonObject = {
            **target,
            "websocket_path": f"/api/browser/cdp/page/{target_id}",
            "protocol": "briareus.v1",
        }
        if api.realtime is not None:
            await api.realtime.publish(
                "browser.runtime",
                "remote_debug.issued",
                {"page_id": payload.page_id, "target_id": target_id},
            )
        return response

    async def browser_set_viewport(self, payload: ViewportPayload, request: Request) -> JsonObject:
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

    async def browser_hard_stop(self, request: Request) -> JsonObject:
        service = self.context.mutation(request)
        try:
            result = await service.web.hard_stop()
            await self.context.publish_management_event(
                service, "browser.runtime.hard_stopped", result
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_restart(self, request: Request) -> JsonObject:
        service = self.context.mutation(request)
        try:
            result = await service.web.restart()
            await self.context.publish_management_event(
                service, "browser.runtime.restarted", result
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_external_status(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        try:
            return await self.context.available().web.external_status()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_external_connect(self, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.web.external_connect()
            if api.realtime is not None:
                event = (
                    "external.connected"
                    if result.get("ok") is True
                    else "external.connect_failed"
                    if result.get("ok") is False
                    else "external.connecting"
                )
                await api.realtime.publish("browser.runtime", event, result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_external_disconnect(self, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.web.external_disconnect()
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "external.disconnected", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def browser_external_reset(self, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.web.external_reset()
            if api.realtime is not None:
                await api.realtime.publish("browser.runtime", "external.reset", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
