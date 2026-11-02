"""Resources-only route projection. Does not mint user or effect permissions."""

from collections.abc import Callable

from cryptography.fernet import Fernet
from fastapi import APIRouter

from common.platform_db import PlatformDatabase
from node_protocol.module_effects import MODULES
from projects.presentation.node_routing import BrowserScopeQuery as BrowserScopeQuery
from projects.presentation.node_routing import NodeRoutingBoundary
from projects.presentation.node_routing import RouteQuery as RouteQuery
from runtime_peer import PeerClient


def route_router(
    resolve_database: Callable[[], PlatformDatabase | None],
    *,
    platform: PeerClient | None = None,
    cipher: Fernet | None = None,
) -> APIRouter:
    router = APIRouter()
    boundary = NodeRoutingBoundary(resolve_database, platform)
    router.add_api_route(
        "/internal/v1/resources/node-route",
        boundary.route,
        methods=["POST"],
        include_in_schema=False,
    )
    for scope in ("browser", "terminal", "analysis", "files"):
        router.add_api_route(
            "/internal/v1/resources/" + scope + "-scope",
            boundary.browser_scope,
            methods=["POST"],
            include_in_schema=False,
        )
    for module in sorted(MODULES):
        router.add_api_route(
            "/internal/v1/resources/node-" + module + "-authority",
            boundary.route,
            methods=["POST"],
            include_in_schema=False,
        )
    if platform is not None and cipher is not None:
        from projects.node_invocation import invocation_router

        router.include_router(
            invocation_router(
                platform=platform,
                cipher=cipher,
                resolve_database=resolve_database,
                resolve_binding=boundary.current_binding,
            )
        )
    return router
