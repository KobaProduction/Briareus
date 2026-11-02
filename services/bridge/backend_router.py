"""Legacy Bridge composition entrypoint for typed backend routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from mcp.types import CallToolRequestParams, CallToolResult

from .application.backend_routing import BackendLocation, BackendRouting
from .domain.backend_failure import call_failure
from .infrastructure.backend_routing import BackendDescriptor as BackendDescriptor
from .infrastructure.backend_routing import BackendSessionGateway
from .presentation.backend_models import (
    BackendDirectoryView,
    BackendView,
)
from .presentation.backend_results import call_reply, catalog_reply, failure_reply


class BackendRouter:
    def __init__[LifespanT](
        self,
        backends: tuple[BackendDescriptor[LifespanT], ...],
        *,
        timeout_provider: Callable[[], Awaitable[float]] | None = None,
    ) -> None:
        self._gateway = BackendSessionGateway(backends, timeout_provider=timeout_provider)
        locations = tuple(
            BackendLocation(backend.name, backend.public_path, backend.purpose)
            for backend in backends
        )
        self._routing = BackendRouting(locations, self._gateway)

    async def describe(self) -> BackendDirectoryView:
        statuses = await self._routing.describe()
        return BackendDirectoryView(
            backends=tuple(
                BackendView(
                    name=status.location.name,
                    public_path=status.location.public_path,
                    purpose=status.location.purpose,
                    status=status.status,
                    tool_count=status.tool_count,
                    error_type=status.error_type,
                )
                for status in statuses
            ),
            count=len(statuses),
        )

    async def tools(self, name: str, *, refresh: bool = False) -> CallToolResult:
        backend = self._routing.location(name)
        try:
            tools = await self._gateway.catalog(backend.name, refresh=refresh)
        except Exception as exc:
            return catalog_reply(backend, (), error_type=type(exc).__name__)
        return catalog_reply(backend, tools)

    async def call(
        self,
        name: str,
        request: CallToolRequestParams,
    ) -> CallToolResult:
        backend = self._routing.location(name)
        try:
            result = await self._gateway.invoke(backend.name, request)
            return call_reply(backend.name, request.name, result)
        except Exception as exc:
            return failure_reply(backend.name, request.name, call_failure(exc))

    async def close(self) -> None:
        await self._gateway.close()
