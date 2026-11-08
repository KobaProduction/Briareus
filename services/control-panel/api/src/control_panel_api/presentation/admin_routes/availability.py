"""Provider-owned API operations are disabled when that MCP is absent from the node."""

from collections.abc import Callable, Coroutine

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from starlette.responses import Response

from .context import WebApiContext


def _provider(path: str) -> str | None:
    section = path.removeprefix("/admin/api/").split("/", 1)[0]
    return {
        "files": "server",
        "terminal": "server",
        "browser": "playwright",
        "analysis": "ghidra",
    }.get(section)


def provider_route(context: WebApiContext) -> type[APIRoute]:
    class AvailableProviderRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[None, None, Response]]:
            original = super().get_route_handler()
            service_id = _provider(self.path)

            async def guarded(request: Request) -> Response:
                if service_id is not None and context.discovery is not None:
                    context.require_user(request)
                    if not await context.discovery.connected(service_id):
                        raise HTTPException(
                            503, detail={"code": "service_unavailable", "service": service_id}
                        )
                return await original(request)

            return guarded

    return AvailableProviderRoute
