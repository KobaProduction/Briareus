"""Typed dispatch of original tool signatures inside the isolated child."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.types import ToolAnnotations

from mcp.types import CallToolRequestParams

from hand_runtime.tool_binding import ValidatedInvocation, bind_invocation
from runtime_peer.terminal_receipts import TerminalReceipt

from .manager import TerminalManager
from .tool_registry import TerminalDecorator
from .tools import register_terminal_tools


class TerminalToolDispatch:
    def __init__(self, manager: TerminalManager) -> None:
        self.tools: dict[
            str, ValidatedInvocation[TerminalReceipt | Awaitable[TerminalReceipt]]
        ] = {}
        register_terminal_tools(self, manager, include_metadata=False)

    def tool(
        self,
        *,
        title: str,
        annotations: ToolAnnotations | None,
    ) -> TerminalDecorator:
        del title, annotations

        def register[**Parameters, Result: TerminalReceipt | Awaitable[TerminalReceipt]](
            function: Callable[Parameters, Result],
        ) -> Callable[Parameters, Result]:
            if function.__name__ in self.tools:
                raise ValueError("Duplicate terminal tool")
            self.tools[function.__name__] = bind_invocation(function)
            return function

        return register

    async def call(self, call: CallToolRequestParams) -> TerminalReceipt:
        result = self.tools[call.name](call)
        return await result if isawaitable(result) else result
