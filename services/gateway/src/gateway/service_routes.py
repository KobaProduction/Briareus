"""One authenticated MCP facade per discovered provider; no aggregate forwarding MCP."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass

from briareus_oidc import OidcTokenVerifier
from briareus_service_catalog import ServiceDefinition
from briareus_service_discovery import ServiceDiscovery
from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.providers.proxy import FastMCPProxy
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Match
from starlette.types import Receive, Scope, Send

from .auth_surfaces import build_service_auth
from .backend_sessions import ProxyClientPool
from .gateway_settings import GatewayAuthSettings
from .settings import GatewaySettings


@dataclass
class _Surface:
    app: Starlette
    auth: RemoteAuthProvider | None


@asynccontextmanager
async def _host_lifespan(app: Starlette, name: str) -> AsyncIterator[None]:
    """AnyIO task groups must enter and exit inside the same owning task."""
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def host() -> None:
        try:
            async with app.router.lifespan_context(app):
                ready.set()
                await stop.wait()
        finally:
            ready.set()

    task = asyncio.create_task(host(), name=f"mcp-facade:{name}")
    try:
        await ready.wait()
        if task.done():
            await task
        yield
    finally:
        stop.set()
        await task


class ServiceMcpRoutes:
    def __init__(
        self,
        discovery: ServiceDiscovery,
        settings: GatewaySettings,
        auth: GatewayAuthSettings,
        timeout: Callable[[], Awaitable[float]],
        *,
        targets: Mapping[str, str | FastMCP[None]] | None = None,
    ) -> None:
        self.discovery = discovery
        self.settings = settings
        self.auth_settings = auth
        self.timeout = timeout
        self.targets = targets or {}
        self.verifier = OidcTokenVerifier(auth) if auth.enabled else None
        self._surfaces: dict[ServiceDefinition, _Surface] = {}
        self._stack = AsyncExitStack()
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        async with self._stack:
            yield

    async def _surface(self, service: ServiceDefinition) -> _Surface:
        async with self._lock:
            if service in self._surfaces:
                return self._surfaces[service]
            auth = build_service_auth(self.auth_settings, service, self.verifier)
            pool = ProxyClientPool(
                self.targets.get(service.id, service.internal_origin + "/mcp"),
                name=service.id,
                timeout_provider=self.timeout,
                size=2,
            )
            proxy = FastMCPProxy(
                client_factory=pool.acquire, name=service.name, lifespan=pool.lifespan
            )
            facade: FastMCP[None] = FastMCP(service.name, auth=auth)
            facade.mount(proxy)
            app = facade.http_app(
                path="/mcp",
                allowed_hosts=list(self.settings.http.allowed_hosts),
                allowed_origins=list(self.settings.http.allowed_origins),
            )
            await self._stack.enter_async_context(_host_lifespan(app, service.id))
            surface = _Surface(app, auth)
            self._surfaces[service] = surface
            return surface

    async def _metadata(
        self, service: ServiceDefinition, scope: Scope, receive: Receive, send: Send
    ) -> None:
        surface = await self._surface(service)
        if surface.auth is not None:
            for route in surface.auth.get_well_known_routes(mcp_path="/mcp"):
                match, child = route.matches(scope)
                if match == Match.FULL:
                    await route.handle({**scope, **child}, receive, send)
                    return
        await JSONResponse({"code": "not_found"}, status_code=404)(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 4404})
            return
        path = scope["path"].rstrip("/")
        snapshot = await self.discovery.snapshot()
        for item in snapshot.services:
            service = ServiceDefinition(id=item.id, name=item.name, group=item.group)
            if path == "/.well-known/oauth-protected-resource" + service.mcp_path:
                await self._metadata(service, scope, receive, send)
                return
            if path != service.mcp_path:
                continue
            if not item.connected:
                await JSONResponse(
                    {"code": "service_unavailable", "service": service.id}, status_code=503
                )(scope, receive, send)
                return
            surface = await self._surface(service)
            prefix = service.mcp_path.removesuffix("/mcp")
            await surface.app({**scope, "root_path": prefix}, receive, send)
            return
        await JSONResponse({"code": "not_found"}, status_code=404)(scope, receive, send)
