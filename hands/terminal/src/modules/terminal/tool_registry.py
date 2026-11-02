"""Registration port retaining original callable signatures."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mcp.types import ToolAnnotations


from runtime_peer.terminal_receipts import TerminalReceipt


class TerminalDecorator(Protocol):
    def __call__[**Parameters, Result: TerminalReceipt | Awaitable[TerminalReceipt]](
        self, function: Callable[Parameters, Result]
    ) -> Callable[Parameters, Result]: ...


class TerminalRegistry(Protocol):
    def tool(
        self,
        *,
        title: str,
        annotations: ToolAnnotations | None,
    ) -> TerminalDecorator: ...
