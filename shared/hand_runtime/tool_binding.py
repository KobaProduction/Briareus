"""Strict SDK request binding shared by synchronous and asynchronous tools."""

from collections.abc import Awaitable, Callable
from functools import partial

from fastmcp.tools import Tool, ToolResult
from mcp.types import CallToolRequestParams, ToolAnnotations
from pydantic import BaseModel, ConfigDict, validate_call
from pydantic.json_schema import JsonSchemaValue

type ValidatedInvocation[Result] = Callable[[CallToolRequestParams], Result]


def bind_invocation[**Parameters, Result](
    function: Callable[Parameters, Result],
) -> ValidatedInvocation[Result]:
    # validate_call owns both parameter binding and post-await return validation.
    validated = validate_call(config=ConfigDict(strict=True), validate_return=True)(function)
    keywords = partial(validated)

    def invoke(call: CallToolRequestParams) -> Result:
        return keywords.func(**(call.arguments or {}))

    return invoke


def bind_delegated_tool(original: Tool, run: Callable[[], Awaitable[ToolResult]]) -> Tool:
    """Keep source metadata while effects use only their original signed request."""
    metadata = Tool(
        name=original.name,
        title=original.title,
        description=original.description,
        parameters=original.parameters,
        output_schema=original.output_schema,
        annotations=original.annotations,
        meta=original.meta,
        icons=original.icons,
    )

    async def delegate(**arguments: object) -> ToolResult:
        # SDK-inserted defaults never replace the original signed request.
        del arguments
        return await run()

    proxy = Tool.from_tool(metadata, transform_fn=delegate, output_schema=metadata.output_schema)
    return proxy.model_copy(update={"parameters": original.parameters})


class _SourceToolRegistration:
    tools: dict[str, ValidatedInvocation[BaseModel | Awaitable[BaseModel]]]
    annotations: dict[str, ToolAnnotations | None]
    _context_clearers: tuple[Callable[[], None], ...]

    def tool[**P, R: BaseModel | Awaitable[BaseModel]](
        self,
        *,
        title: str | None = None,
        annotations: ToolAnnotations | None = None,
        output_schema: JsonSchemaValue | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        del title, output_schema  # Display metadata belongs to the public MCP registration.

        def register(function: Callable[P, R]) -> Callable[P, R]:
            if function.__name__ in self.tools:
                raise ValueError("Duplicate provider tool")
            self.tools[function.__name__] = bind_invocation(function)
            self.annotations[function.__name__] = annotations
            return function

        return register

    def clear(self) -> None:
        for clear_context in self._context_clearers:
            clear_context()
        self.tools.clear()
        self.annotations.clear()
