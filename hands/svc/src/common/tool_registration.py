"""The callable-registration boundary used by MCP and private child dispatch."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from mcp.types import ToolAnnotations
from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue


class ToolRegistrar(Protocol):
    def tool[**P, R: BaseModel | Awaitable[BaseModel]](
        self,
        *,
        title: str | None = None,
        annotations: ToolAnnotations | None = None,
        output_schema: JsonSchemaValue | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]: ...
