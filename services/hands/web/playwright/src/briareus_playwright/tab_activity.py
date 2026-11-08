from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from inspect import signature
from typing import TYPE_CHECKING, Concatenate

from briareus_json_values import StrictModel
from pydantic import Field

if TYPE_CHECKING:
    from .browser import BrowserManager


class TabPolicy(StrictModel):
    max_tabs: int = Field(20, ge=1, le=100)
    idle_close_enabled: bool = True
    idle_timeout_seconds: int = Field(300, ge=30, le=86400)


class TabActivity:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.last_used: dict[str, float] = {}
        self.busy: dict[str, int] = {}

    def touch(self, page_id: str) -> None:
        if page_id in self.last_used:
            self.last_used[page_id] = self.clock()

    def register(self, page_id: str) -> None:
        self.last_used.setdefault(page_id, self.clock())

    def forget(self, page_id: str) -> None:
        self.last_used.pop(page_id, None)

    def idle(self, page_id: str, timeout: int) -> bool:
        last = self.last_used.get(page_id)
        return (
            last is not None
            and not self.busy.get("")
            and not self.busy.get(page_id)
            and self.clock() - last >= timeout
        )

    @asynccontextmanager
    async def operation(self, page_id: str) -> AsyncIterator[None]:
        self.touch(page_id)
        self.busy[page_id] = self.busy.get(page_id, 0) + 1
        try:
            yield
        finally:
            count = self.busy[page_id] - 1
            if count:
                self.busy[page_id] = count
            else:
                del self.busy[page_id]
            self.touch(page_id)


def page_interaction[**P, R](
    method: Callable[Concatenate[BrowserManager, P], Awaitable[R]],
) -> Callable[Concatenate[BrowserManager, P], Awaitable[R]]:
    parameters = signature(method)

    async def wrapped(self: BrowserManager, /, *args: P.args, **kwargs: P.kwargs) -> R:
        page_id = parameters.bind(self, *args, **kwargs).arguments.get("page_id", "")
        async with self.page_operation(page_id if isinstance(page_id, str) else ""):
            return await method(self, *args, **kwargs)

    wrapped.__name__ = method.__name__
    wrapped.__doc__ = method.__doc__
    return wrapped
