"""Execute once under the signed deadline and configured execution budget."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class DispatchNodeTool[ResultT]:
    def __init__(
        self,
        execute: Callable[[], Awaitable[ResultT]],
        *,
        clock: Callable[[], float],
        execution_timeout: Callable[[], float | None],
    ) -> None:
        self._execute = execute
        self._clock, self._execution_timeout = clock, execution_timeout

    async def execute(
        self,
        *,
        expires_at: float,
    ) -> ResultT:
        async with asyncio.timeout(self._execution_timeout()):
            result = await self._execute()
        if expires_at <= self._clock():
            raise ValueError("Execution authority expired")
        return result
