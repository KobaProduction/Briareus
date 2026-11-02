"""Ordered operator scenarios, independent of WebSocket, browser SDK and CDP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, Self

from web_runtime.domain.operator import (
    MouseInput,
    OperatorCommand,
    OperatorOwner,
    OperatorSelection,
    OperatorViolation,
)


class OperatorBrowser(Protocol):
    async def acquire(self) -> OperatorOwner: ...
    async def release(self, owner: str) -> None: ...
    async def selected(self, owner: str) -> str: ...
    async def select(self, owner: str, page: str) -> None: ...
    async def set_label(self, owner: str, page: str, label: str) -> None: ...
    async def set_access(self, owner: str, scope: str, page: str, allowed: bool) -> None: ...
    async def navigate(self, owner: str, page: str, url: str) -> None: ...
    async def new_page(self, owner: str, url: str) -> str: ...
    async def reopen_page(self, owner: str) -> str: ...
    async def clean_browser(self, owner: str) -> str: ...
    async def page_action(self, owner: str, page: str, action: str) -> None: ...
    async def mouse(self, owner: str, page: str, event: MouseInput) -> None: ...
    async def key(self, owner: str, page: str, key: str) -> None: ...
    async def text(self, owner: str, page: str, text: str) -> None: ...


class OperatorEvents(Protocol):
    async def state(self, owner: str) -> None: ...
    async def start_stream(self, owner: str, page: str) -> None: ...
    async def stop_stream(self) -> None: ...


@dataclass
class OperatorSession:
    browser: OperatorBrowser
    events: OperatorEvents
    owner: str
    selection: OperatorSelection

    @classmethod
    async def acquire(cls, browser: OperatorBrowser, events: OperatorEvents) -> Self:
        owner = await browser.acquire()
        return cls(browser, events, owner.token, OperatorSelection(owner.selected_page_id))

    async def start(self) -> None:
        await self.events.state(self.owner)
        if self.selection.page_id:
            await self.events.start_stream(self.owner, self.selection.page_id)

    async def close(self) -> None:
        await self.events.stop_stream()
        await self.browser.release(self.owner)

    async def select_page(self, page: str) -> None:
        await self.browser.select(self.owner, page)
        self.selection.page_id = page
        await self.events.stop_stream()
        await self.events.start_stream(self.owner, page)
        await self.events.state(self.owner)

    async def handle(self, command: OperatorCommand) -> bool:
        if command.action == "release":
            return False
        handlers: dict[str, Callable[[OperatorCommand], Awaitable[None]]] = {
            "select_page": self._select,
            "refresh_state": self._refresh,
            "set_label": self._label,
            "set_page_agent_access": self._access,
            "set_agent_access": self._access,
            "set_developer_access": self._access,
            "navigate": self._navigate,
            "new_page": self._new_page,
            "reopen_closed_page": self._reopen,
            "clean_app": self._clean_app,
            "clean_browser": self._clean_browser,
            "back": self._page_action,
            "reload": self._page_action,
            "close_page": self._close_page,
            "mouse": self._mouse,
            "key": self._key,
            "text": self._text,
        }
        handler = handlers.get(command.action)
        if handler is not None:
            await handler(command)
        return True

    async def _select(self, command: OperatorCommand) -> None:
        await self.select_page(command.page_id)

    async def _refresh(self, _command: OperatorCommand) -> None:
        await self.events.state(self.owner)

    async def _label(self, command: OperatorCommand) -> None:
        await self.browser.set_label(self.owner, command.page_id, command.value)
        await self.events.state(self.owner)

    async def _access(self, command: OperatorCommand) -> None:
        await self.browser.set_access(
            self.owner,
            command.action,
            command.page_id,
            command.access(),
        )
        await self.events.state(self.owner)

    async def _navigate(self, command: OperatorCommand) -> None:
        await self.browser.navigate(
            self.owner,
            self.selection.require_selected(),
            command.value,
        )
        await self.events.state(self.owner)

    async def _new_page(self, command: OperatorCommand) -> None:
        await self.select_page(await self.browser.new_page(self.owner, command.value))

    async def _reopen(self, _command: OperatorCommand) -> None:
        await self.select_page(await self.browser.reopen_page(self.owner))

    async def _clean_app(self, _command: OperatorCommand) -> None:
        await self.browser.page_action(self.owner, self.selection.require_selected(), "clean_app")
        await self.events.state(self.owner)

    async def _clean_browser(self, _command: OperatorCommand) -> None:
        await self.events.stop_stream()
        self.selection.page_id = await self.browser.clean_browser(self.owner)
        if self.selection.page_id:
            await self.events.start_stream(self.owner, self.selection.page_id)
        await self.events.state(self.owner)

    async def _page_action(self, command: OperatorCommand) -> None:
        await self.browser.page_action(self.owner, self.selection.page_id, command.action)
        await self.events.state(self.owner)

    async def _close_page(self, _command: OperatorCommand) -> None:
        await self.browser.page_action(self.owner, self.selection.page_id, "close_page")
        next_page = await self.browser.selected(self.owner)
        if next_page:
            await self.select_page(next_page)
            return
        await self.events.stop_stream()
        self.selection.page_id = ""
        await self.events.state(self.owner)

    async def _mouse(self, command: OperatorCommand) -> None:
        if command.mouse is None:
            raise OperatorViolation("mouse event required")
        await self.browser.mouse(
            self.owner,
            self.selection.input_target(command.page_id),
            command.mouse,
        )

    async def _key(self, command: OperatorCommand) -> None:
        await self.browser.key(
            self.owner,
            self.selection.input_target(command.page_id),
            command.value,
        )

    async def _text(self, command: OperatorCommand) -> None:
        await self.browser.text(
            self.owner,
            self.selection.input_target(command.page_id),
            command.value,
        )
