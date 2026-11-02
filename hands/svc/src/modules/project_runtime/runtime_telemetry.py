"""Compatibility exports for the shared project runtime client implementation."""

import asyncio as asyncio
import logging as logging
import time as time
from collections.abc import AsyncIterator as AsyncIterator
from contextlib import asynccontextmanager as asynccontextmanager
from contextlib import suppress as suppress
from dataclasses import dataclass as dataclass
from dataclasses import field as field
from typing import TypedDict as TypedDict

from fastmcp import FastMCP as FastMCP
from fastmcp.server.middleware import CallNext as CallNext
from fastmcp.server.middleware import Middleware as Middleware
from fastmcp.server.middleware import MiddlewareContext as MiddlewareContext
from fastmcp.tools import ToolResult as ToolResult
from starlette.applications import Starlette as Starlette

from project_runtime_client.application.telemetry_lifespan import (
    with_runtime_telemetry as with_runtime_telemetry,
)
from project_runtime_client.runtime_telemetry import _ALLOWED as _ALLOWED
from project_runtime_client.runtime_telemetry import _EVENT_BATCH_LIMIT as _EVENT_BATCH_LIMIT
from project_runtime_client.runtime_telemetry import _EVENT_QUEUE_LIMIT as _EVENT_QUEUE_LIMIT
from project_runtime_client.runtime_telemetry import _HEARTBEAT_SECONDS as _HEARTBEAT_SECONDS
from project_runtime_client.runtime_telemetry import _LOG as _LOG
from project_runtime_client.runtime_telemetry import _TOOL_FAMILIES as _TOOL_FAMILIES
from project_runtime_client.runtime_telemetry import (
    BoundedRuntimeToolEvents as BoundedRuntimeToolEvents,
)
from project_runtime_client.runtime_telemetry import EmptyMcpLifespanState as EmptyMcpLifespanState
from project_runtime_client.runtime_telemetry import RuntimeTelemetry as RuntimeTelemetry
from project_runtime_client.runtime_telemetry import (
    SafeRuntimeToolTelemetry as SafeRuntimeToolTelemetry,
)
from project_runtime_client.runtime_telemetry import (
    _OnlySanitizedRuntimeLogs as _OnlySanitizedRuntimeLogs,
)
from project_runtime_client.runtime_telemetry import build_runtime_mcp as build_runtime_mcp
from service_runtime.events import InvocationEvent as InvocationEvent
from service_runtime.observability import CompositeObservabilitySink as CompositeObservabilitySink
from service_runtime.observability import OpenTelemetrySink as OpenTelemetrySink
from service_runtime.observability import build_observability as build_observability
from service_runtime.settings import ObservabilitySettings as ObservabilitySettings
