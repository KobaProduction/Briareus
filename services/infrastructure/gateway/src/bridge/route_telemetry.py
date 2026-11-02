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
from gateway_runtime.route_telemetry import _route as _route


class RouteTelemetry(_SharedRouteTelemetry):
    """Keep route labels owned by this Gateway entrypoint."""

    _classify = staticmethod(_route)
