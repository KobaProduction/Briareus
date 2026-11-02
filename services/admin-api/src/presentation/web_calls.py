"""Retained calls HTTP adapters with focused dependencies."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from application.invocation_contracts import InvocationDocument
from application.panel_views import (
    CallsDeleted,
    ItemDeleted,
    PanelCallPage,
)
from application.services import (
    InvocationAuditService,
)
from application.web_events import AdminWebEvents
from domain.telemetry import InvocationQuery
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from presentation.call_stream import stream_calls
from presentation.web_admission import WebAdmission


def _encode_call_cursor(occurred_at: datetime, invocation_id: str) -> str:
    payload = json.dumps(
        [occurred_at.astimezone(UTC).isoformat(), invocation_id],
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_call_cursor(value: str) -> tuple[datetime, str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(decoded, list) or len(decoded) != 2:
            raise ValueError("invalid cursor payload")
        occurred_at = datetime.fromisoformat(str(decoded[0]))
        invocation_id = str(decoded[1]).strip()
        if not invocation_id:
            raise ValueError("invalid cursor id")
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        else:
            occurred_at = occurred_at.astimezone(UTC)
        return occurred_at, invocation_id
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="invalid calls cursor") from exc


@dataclass(eq=False, repr=False)
class WebCallController:
    admission: WebAdmission
    audit: InvocationAuditService | None
    events: AdminWebEvents

    def mount(self, router: APIRouter) -> None:
        router.get("/calls")(self.calls)
        router.delete("/calls")(self.clear_calls)
        router.delete("/calls/{call_id}")(self.delete_call)
        router.get("/calls/stream")(self.calls_stream)

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
    ) -> PanelCallPage:
        self.admission.require_user(request)
        cursor_at: datetime | None = None
        cursor_id = ""
        if cursor:
            cursor_at, cursor_id = _decode_call_cursor(cursor)
        page = await self.admission.available(self.audit).query(
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
            )
        )
        next_cursor = (
            _encode_call_cursor(page.next_cursor_at, page.next_cursor_id)
            if page.next_cursor_at is not None and page.next_cursor_id
            else ""
        )
        return PanelCallPage(
            events=[InvocationDocument(root=item) for item in page.events],
            count=page.count,
            total=page.total,
            limit=limit,
            offset=offset,
            has_more=page.has_more,
            next_cursor=next_cursor,
        )

    async def clear_calls(self, request: Request) -> CallsDeleted:
        api = self.admission.mutation(request, self.audit)
        removed = await api.clear()
        response: CallsDeleted = CallsDeleted(deleted=removed)
        await self.events.publish("calls.cleared", response)
        return response

    async def delete_call(self, call_id: str, request: Request) -> ItemDeleted:
        api = self.admission.mutation(request, self.audit)
        removed = await api.delete(call_id)
        if not removed:
            raise HTTPException(status_code=404, detail="call not found")
        response: ItemDeleted = ItemDeleted(deleted=True, id=call_id)
        await self.events.publish("calls.deleted", response)
        return response

    async def calls_stream(self, request: Request) -> StreamingResponse:
        self.admission.require_user(request)
        audit = self.admission.available(self.audit)
        return StreamingResponse(
            stream_calls(audit, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
