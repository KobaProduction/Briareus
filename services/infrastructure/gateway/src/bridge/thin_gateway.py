"""Public static Panel and transparent /api reverse proxy.

Authentication, sessions, identity and all API routing belong to Admin API.
No Gateway C2 adapter, JWT verifier or special Identity destination exists.
"""

from __future__ import annotations

import asyncio as asyncio
import re as re
from collections.abc import AsyncIterator as AsyncIterator
from contextlib import asynccontextmanager as asynccontextmanager
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote as quote

import httpx as httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request as Request
from starlette.responses import JSONResponse as JSONResponse
from starlette.responses import Response as Response
from starlette.responses import StreamingResponse as StreamingResponse
from starlette.routing import Route

from gateway_runtime.thin_gateway import _API_UPSTREAM as _API_UPSTREAM
from gateway_runtime.thin_gateway import _ASSET_TYPES as _ASSET_TYPES
from gateway_runtime.thin_gateway import _HOP_HEADERS as _HOP_HEADERS
from gateway_runtime.thin_gateway import _METHODS as _METHODS
from gateway_runtime.thin_gateway import _PANEL_ASSET as _PANEL_ASSET
from gateway_runtime.thin_gateway import _PANEL_UPSTREAM as _PANEL_UPSTREAM
from gateway_runtime.thin_gateway import _PROXY_ASSERTIONS as _PROXY_ASSERTIONS
from gateway_runtime.thin_gateway import _PUBLIC_FILES as _PUBLIC_FILES
from gateway_runtime.thin_gateway import _STATIC_TYPE as _STATIC_TYPE
from gateway_runtime.thin_gateway import _TIMEOUT as _TIMEOUT
from gateway_runtime.thin_gateway import ThinGateway as _SharedThinGateway
from gateway_runtime.thin_gateway import _api_headers as _api_headers
from gateway_runtime.thin_gateway import _media_type as _media_type
from gateway_runtime.thin_gateway import _raw_path as _raw_path

from .route_telemetry import RouteTelemetry
from .single_origin import SingleOriginGuard, unavailable_routes


@dataclass(frozen=True, slots=True)
class RouteSpec:
    """Public route template and its fixed internal service destination."""

    template: str
    target: Literal["panel-ui", "panel-api"]


# Runtime routing policy contains no principal, permissions or Identity paths.
_ROUTE_TABLE: tuple[RouteSpec, ...] = (
    RouteSpec("/", "panel-ui"),
    RouteSpec("/robots.txt", "panel-ui"),
    RouteSpec("/sitemap.xml", "panel-ui"),
    RouteSpec("/panel", "panel-ui"),
    RouteSpec("/panel/{path:path}", "panel-ui"),
    RouteSpec("/api", "panel-api"),
    RouteSpec("/api/{path:path}", "panel-api"),
)


class ThinGateway(_SharedThinGateway):
    """Keep the local transport type over the canonical legacy proxy."""


def build_app() -> Starlette:
    transport = ThinGateway()
    handlers = {"panel-ui": transport.static, "panel-api": transport.api}
    return Starlette(
        routes=[
            *[
                Route(spec.template, handlers[spec.target], methods=_METHODS)
                for spec in _ROUTE_TABLE
            ],
            *unavailable_routes(),
        ],
        middleware=[Middleware(SingleOriginGuard), Middleware(RouteTelemetry)],
        lifespan=transport.lifespan,
    )
