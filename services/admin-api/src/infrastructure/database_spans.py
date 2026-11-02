"""Preserve async repository signatures while recording database span metadata."""

from collections.abc import Awaitable, Callable
from functools import update_wrapper
from typing import ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.trace import SpanKind

_P = ParamSpec("_P")
_R = TypeVar("_R")
_DB_TRACER = trace.get_tracer("mcp-bridge.admin-api-db")


def db_span(
    operation: str,
) -> Callable[[Callable[_P, Awaitable[_R]]], Callable[_P, Awaitable[_R]]]:
    def decorate(function: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
        async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            with _DB_TRACER.start_as_current_span(
                f"admin-api.db.{operation}",
                kind=SpanKind.INTERNAL,
                attributes={
                    "db.namespace": "admin-api",
                    "db.operation.name": operation,
                },
            ):
                return await function(*args, **kwargs)

        update_wrapper(wrapped, function)
        return wrapped

    return decorate
