from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal

from briareus_json_values import JsonObject
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from control_panel_api.application.services import InvocationAuditService
from control_panel_api.domain.telemetry import InvocationQuery

from .context import WebApiContext
from .contracts import _decode_call_cursor, _encode_call_cursor, _oauth_json


class CallsRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/calls", self.calls, methods=["GET"])
        router.add_api_route("/calls", self.clear_calls, methods=["DELETE"])
        router.add_api_route("/calls/{call_id}", self.delete_call, methods=["DELETE"])
        router.add_api_route("/calls/stream", self.calls_stream, methods=["GET"])
        router.add_api_route("/oauth-sessions", self.oauth_sessions, methods=["GET"])

    async def calls(
        self,
        request: Request,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        cursor: str = Query("", max_length=512),
        module: str = Query("", max_length=64),
        tool: str = Query("", max_length=256),
        provider: str = Query("", max_length=32),
        account_id: str = Query("", max_length=128),
        call_status: Literal["success", "error"] | None = Query(None, alias="status"),
        search: str = Query("", max_length=256),
    ) -> JsonObject:
        self.context.require_user(request)
        cursor_at: datetime | None = None
        cursor_id = ""
        if cursor:
            cursor_at, cursor_id = _decode_call_cursor(cursor)
        page = await asyncio.to_thread(
            self.context.available().audit.query,
            InvocationQuery(
                limit=limit,
                offset=offset,
                cursor_at=cursor_at,
                cursor_id=cursor_id,
                module=module.strip(),
                tool=tool.strip(),
                provider=provider.strip(),
                account_id=account_id.strip(),
                status=call_status,
                search=search.strip(),
            ),
        )
        next_cursor = (
            _encode_call_cursor(page.next_cursor_at, page.next_cursor_id)
            if page.next_cursor_at is not None and page.next_cursor_id
            else ""
        )
        return {
            "events": [item.model_dump(mode="json") for item in page.events],
            "count": page.count,
            "total": page.total,
            "limit": limit,
            "offset": offset,
            "has_more": page.has_more,
            "next_cursor": next_cursor,
        }

    async def clear_calls(self, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        removed = await asyncio.to_thread(api.audit.clear)
        response: JsonObject = {"deleted": removed}
        await self.context.publish_management_event(api, "calls.cleared", response)
        return response

    async def delete_call(self, call_id: str, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        removed = await asyncio.to_thread(api.audit.delete, call_id)
        if not removed:
            raise HTTPException(status_code=404, detail="call not found")
        response: JsonObject = {"deleted": True, "id": call_id}
        await self.context.publish_management_event(api, "calls.deleted", response)
        return response

    async def calls_stream(self, request: Request) -> StreamingResponse:
        self.context.require_user(request)
        audit = self.context.available().audit
        return StreamingResponse(
            self.call_events(request, audit),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    async def oauth_sessions(
        self, request: Request, limit: int = Query(200, ge=1, le=1000)
    ) -> JsonObject:
        self.context.require_user(request)
        items = await asyncio.to_thread(self.context.available().oauth_sessions.recent, limit=limit)
        return {"sessions": [_oauth_json(item) for item in items], "count": len(items)}

    async def call_events(
        self, request: Request, audit: InvocationAuditService
    ) -> AsyncIterator[str]:
        seen: set[str] = set()
        initial = await asyncio.to_thread(audit.recent, limit=100)
        for item in reversed(initial):
            seen.add(item.id)
            yield f"data: {json.dumps(item.model_dump(mode='json'), ensure_ascii=False)}\\n\\n"
        while not await request.is_disconnected():
            latest = await asyncio.to_thread(audit.recent, limit=100)
            fresh = [item for item in reversed(latest) if item.id not in seen]
            for item in fresh:
                seen.add(item.id)
                payload_json = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
                yield f"data: {payload_json}\\n\\n"
            if len(seen) > 5000:
                seen = {item.id for item in latest}
            yield ": keepalive\\n\\n"
            await asyncio.sleep(1)
