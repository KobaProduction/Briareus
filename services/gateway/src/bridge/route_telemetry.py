"""Bounded transport-only request observations; no paths, query, tokens or bodies."""

from __future__ import annotations

import logging as logging
from time import monotonic as monotonic

from starlette.requests import Request as Request
from starlette.types import ASGIApp as ASGIApp
from starlette.types import Message as Message
from starlette.types import Receive as Receive
from starlette.types import Scope as Scope
from starlette.types import Send as Send

from gateway_runtime.route_telemetry import _LOG as _LOG
from gateway_runtime.route_telemetry import _SUPPORTED as _SUPPORTED
from gateway_runtime.route_telemetry import RouteTelemetry as _SharedRouteTelemetry
from gateway_runtime.route_telemetry import _bucket as _bucket

from .single_origin import MCP_ENDPOINTS


def _route(path: str) -> tuple[str, str]:
    if path in {"/", "/robots.txt", "/sitemap.xml"}:
        return "landing", "panel-ui"
    if path == "/panel" or path.startswith("/panel/"):
        # Constant-cardinality route label; never include SPA path or asset URL.
        return "panel", "panel-ui"
    if path == "/api" or path.startswith("/api/"):
        return "api", "panel-api"
    if path in MCP_ENDPOINTS.values():
        return "mcp-admission", "authorization"
    if path.startswith("/hands/"):
        return "hands-disabled", "deny"
    return "other", "deny"


class RouteTelemetry(_SharedRouteTelemetry):
    """Keep route labels owned by this Gateway entrypoint."""

    _classify = staticmethod(_route)
