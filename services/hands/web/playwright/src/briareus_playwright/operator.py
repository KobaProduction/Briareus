from __future__ import annotations

import asyncio
import contextlib
import hmac
from collections.abc import Awaitable, Callable

from briareus_json_values import JsonObject
from playwright.async_api import Error as PlaywrightError
from starlette.websockets import WebSocket, WebSocketDisconnect

from briareus_playwright.browser import BrowserError, BrowserManager

from .operator_protocol import (
    AccessCommand,
    ClipboardCommand,
    KeyCommand,
    LabelCommand,
    MouseCommand,
    OperatorCommand,
    PageCommand,
    StateCommand,
    TextCommand,
    parse_command,
)
from .operator_stream import stream_operator_page


def _bearer_token(websocket: WebSocket) -> str:
    scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.casefold() == "bearer" else ""


class _OperatorSession:
    def __init__(
        self, websocket: WebSocket, browser: BrowserManager, owner: str, page_id: str
    ) -> None:
        self.websocket = websocket
        self.browser = browser
        self.owner = owner
        self.selected_page_id = page_id
        self.stream_task: asyncio.Task[None] | None = None

    async def send_state(self) -> None:
        state = await self.browser.operator_state(self.owner)
        selected = str(state.get("selected_page_id") or "")
        if selected != self.selected_page_id:
            await self.stop_stream()
            self.selected_page_id = selected
        self.start_stream()
        state["type"] = "state"
        await self.websocket.send_json(state)

    async def stop_stream(self) -> None:
        if self.stream_task is not None:
            self.stream_task.cancel()
            await asyncio.gather(self.stream_task, return_exceptions=True)
            self.stream_task = None

    def start_stream(self) -> None:
        if self.selected_page_id and (self.stream_task is None or self.stream_task.done()):
            self.stream_task = asyncio.create_task(
                stream_operator_page(
                    self.websocket, self.browser, self.owner, self.selected_page_id
                ),
                name="browser-operator-stream",
            )

            self.stream_task.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )

    async def select_page(self, page_id: str) -> None:
        await self.browser.operator_select_page(self.owner, page_id)
        self.selected_page_id = page_id
        await self.stop_stream()
        self.start_stream()
        await self.send_state()

    def input_page_id(self, requested: str) -> str:
        page_id = requested or self.selected_page_id
        if not page_id or page_id != self.selected_page_id:
            raise BrowserError("browser input target is not active for this operator")
        return page_id

    def required_page_id(self) -> str:
        if not self.selected_page_id:
            raise BrowserError("no browser page selected")
        return self.selected_page_id

    async def run(self) -> None:
        await self.send_state()
        self.start_stream()
        while True:
            raw = await self.websocket.receive_text()
            command: OperatorCommand | None = None
            try:
                command = parse_command(raw)
                if isinstance(command, StateCommand) and command.type == "release":
                    return
                if command is not None:
                    await self.dispatch(command)
            except (BrowserError, ValueError, PlaywrightError) as exc:
                await self.send_error(exc, command)

    async def send_error(self, exc: Exception, command: OperatorCommand | None) -> None:
        payload: JsonObject = {"type": "error", "message": str(exc)}
        if isinstance(command, ClipboardCommand) or (
            isinstance(command, PageCommand) and command.type == "navigate" and command.request_id
        ):
            payload["request_id"] = command.request_id
        code = getattr(exc, "code", None)
        if isinstance(code, str):
            payload["code"] = code
        limit = getattr(exc, "limit", None)
        if isinstance(limit, int):
            payload["max_tabs"] = limit
        await self.websocket.send_json(payload)

    async def dispatch(self, command: OperatorCommand) -> None:
        if isinstance(command, StateCommand):
            await self.state_command(command)
        elif isinstance(command, PageCommand):
            await self.page_command(command)
        elif isinstance(command, AccessCommand):
            await self.access_command(command)
        elif isinstance(command, LabelCommand):
            await self.browser.operator_set_page_label(self.owner, command.page_id, command.label)
            await self.send_state()
        elif isinstance(command, MouseCommand):
            await self.mouse_command(command)
        elif isinstance(command, KeyCommand):
            await self.browser.operator_key(
                self.owner, self.input_page_id(command.page_id), command.key
            )
        elif isinstance(command, ClipboardCommand):
            await self.clipboard_command(command)
        elif isinstance(command, TextCommand):
            await self.browser.operator_text(
                self.owner, self.input_page_id(command.page_id), command.text
            )

    async def clipboard_command(self, command: ClipboardCommand) -> None:
        page_id = self.input_page_id(command.page_id)
        text = await self.browser.operator_read_selection(self.owner, page_id)
        await self.websocket.send_json({
            "type": "clipboard", "request_id": command.request_id,
            "page_id": page_id, "text": text,
        })

    async def page_command(self, command: PageCommand) -> None:
        if command.type == "select_page":
            await self.select_page(command.page_id)
        elif command.type == "new_page":
            result = await self.browser.operator_new_page(self.owner, command.url)
            await self.select_page(str(result["page_id"]))
        elif command.type == "close_page":
            await self.close_page(command.page_id or self.selected_page_id)
        else:
            page_id = self.required_page_id()
            result = await self.browser.operator_navigate(self.owner, page_id, command.url)
            if command.request_id:
                await self.websocket.send_json({
                    "type": "navigation_complete",
                    "request_id": command.request_id,
                    "page_id": page_id,
                    "url": result.get("url", ""),
                })
            await self.send_state()

    async def access_command(self, command: AccessCommand) -> None:
        if command.type == "set_page_agent_access":
            await self.browser.operator_set_page_agent_access(
                self.owner, command.page_id, command.allowed
            )
        elif command.type == "set_agent_access":
            await self.browser.operator_set_agent_access(self.owner, command.allowed)
        else:
            await self.browser.operator_set_developer_access(self.owner, command.allowed)
        await self.send_state()

    async def mouse_command(self, command: MouseCommand) -> None:
        await self.browser.operator_mouse(
            self.owner,
            self.input_page_id(command.page_id),
            event_type=command.event,
            x=command.x,
            y=command.y,
            button=command.button,
            click_count=command.click_count,
            buttons=command.buttons,
            delta_x=command.delta_x,
            delta_y=command.delta_y,
        )

    async def state_command(self, command: StateCommand) -> None:
        handlers: dict[str, Callable[[], Awaitable[None]]] = {
            "refresh_state": self.send_state,
            "back": self.back,
            "reload": self.reload,
            "clean_app": self.clean_app,
            "close_all_pages": self.close_all_pages,
            "clean_browser": self.clean_browser,
            "reopen_closed_page": self.reopen_closed_page,
        }
        await handlers[command.type]()

    async def back(self) -> None:
        await self.browser.operator_back(self.owner, self.selected_page_id)
        await self.send_state()

    async def reload(self) -> None:
        await self.browser.operator_reload(self.owner, self.selected_page_id)
        await self.send_state()

    async def clean_app(self) -> None:
        await self.browser.operator_clean_app(self.owner, self.required_page_id())
        await self.send_state()

    async def clean_browser(self) -> None:
        await self.stop_stream()
        result = await self.browser.operator_clean_browser(self.owner)
        self.selected_page_id = str(result.get("selected_page_id") or "")
        self.start_stream()
        await self.send_state()

    async def reopen_closed_page(self) -> None:
        result = await self.browser.operator_reopen_closed_page(self.owner)
        await self.select_page(str(result["page_id"]))

    async def close_page(self, page_id: str) -> None:
        await self.browser.operator_close_page(self.owner, page_id)
        if page_id != self.selected_page_id:
            await self.send_state()
            return
        state = await self.browser.operator_state(self.owner)
        next_page = str(state.get("selected_page_id") or "")
        if next_page:
            await self.select_page(next_page)
        else:
            await self.stop_stream()
            self.selected_page_id = ""
            await self.send_state()

    async def close_all_pages(self) -> None:
        await self.stop_stream()
        await self.browser.operator_close_all_pages(self.owner)
        self.selected_page_id = ""
        await self.send_state()


async def browser_operator_websocket(
    websocket: WebSocket, *, browser: BrowserManager, service_token: str
) -> None:
    supplied = _bearer_token(websocket)
    if not supplied or not hmac.compare_digest(supplied, service_token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        owner = await browser.operator_acquire()
    except BrowserError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=4409)
        return
    session = _OperatorSession(
        websocket, browser, str(owner["owner_token"]), str(owner.get("selected_page_id") or "")
    )
    try:
        await session.run()
    except WebSocketDisconnect:
        pass
    finally:
        await session.stop_stream()
        await browser.operator_release(session.owner)
        # The peer may have already disconnected (1006) while we released the
        # stream and ownership. Do not log an ASGI error for this normal race.
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close()
