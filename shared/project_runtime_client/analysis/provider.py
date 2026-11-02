from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Sequence
from copy import deepcopy

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.providers import Provider
from fastmcp.tools import FunctionTool, Tool
from fastmcp.utilities.components import FastMCPComponent
from mcp.types import CallToolRequestParams, CallToolResult
from mcp.types import Tool as McpTool

from hand_runtime.provider_schemas import WRAPPED_PROVIDER_RESULT_SCHEMA
from service_runtime.mcp_client_pool import PersistentMcpClientPool
from service_runtime.mcp_http import mcp_http_client

from .catalog_queries import check_catalog, search_catalog
from .catalog_views import (
    AnalysisToolCheck,
    AnalysisToolSearch,
    AnalysisVocabulary,
)
from .configuration import AnalysisBackendConfiguration
from .input_schema import analysis_schema, normalize_arguments, tool_alias
from .result import decode_call_result
from .terminology import (
    analysis_surface_violations,
    analysis_text,
    analysis_tool_name,
    analysis_vocabulary,
)


class AnalysisProviderError(RuntimeError):
    pass


_OUTPUT_SCHEMA = WRAPPED_PROVIDER_RESULT_SCHEMA


def _rewrite_catalog_text(text: str, aliases: dict[str, str]) -> str:
    value = text
    for private_name, public_name in sorted(
        aliases.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if private_name == public_name:
            continue
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(private_name)}(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        value = pattern.sub(public_name, value)
    return value


def _rewrite_catalog_references(tool: McpTool, aliases: dict[str, str]) -> McpTool:
    adapted = tool.model_copy(deep=True)
    pending: list[object] = [adapted.input_schema]
    while pending:
        container = pending.pop()
        if isinstance(container, dict):
            _rewrite_schema_fields(container, pending, aliases)
        elif isinstance(container, list):
            _rewrite_schema_items(container, pending, aliases)
    return adapted


def _rewrite_schema_fields(native: object, pending: list[object], aliases: dict[str, str]) -> None:
    # These are SDK schema members, never an application data contract.
    if not isinstance(native, dict):
        raise TypeError("Native schema properties required")
    for key, item in native.items():
        if isinstance(item, str):
            native[key] = _rewrite_catalog_text(item, aliases)
        else:
            pending.append(item)


def _rewrite_schema_items(native: object, pending: list[object], aliases: dict[str, str]) -> None:
    if not isinstance(native, list):
        raise TypeError("Native schema array required")
    for index, item in enumerate(native):
        if isinstance(item, str):
            native[index] = _rewrite_catalog_text(item, aliases)
        else:
            pending.append(item)


class AnalysisToolProvider(Provider):
    """Expose the private backend through a fully separated Analysis vocabulary."""

    def __init__(self, settings: AnalysisBackendConfiguration) -> None:
        super().__init__()
        self.settings = settings
        self._cache: tuple[float, list[Tool]] | None = None
        self._cache_lock = asyncio.Lock()
        self._backend_pool = PersistentMcpClientPool(
            self._backend_client,
            name="analysis-ghidra",
            size=4,
        )

    def _backend_url(self) -> str:
        value = self.settings.backend_url.strip()
        if not value:
            raise AnalysisProviderError("analysis backend URL is not configured")
        return value

    def _backend_client(self) -> Client[StreamableHttpTransport]:
        transport = StreamableHttpTransport(
            self._backend_url(),
            headers={"X-Koba-Proxy-Origin": "analysis"},
            httpx_client_factory=mcp_http_client,
        )
        return Client(transport, timeout=None)

    async def get_tasks(self) -> Sequence[FastMCPComponent]:
        """Analysis tools are dynamic RPC facades, not background-task registrations."""
        return []

    async def _list_tools(self) -> Sequence[Tool]:
        ttl = self.settings.schema_cache_ttl_seconds
        now = time.monotonic()
        cached = self._cache
        if ttl > 0 and cached is not None and cached[0] > now:
            return list(cached[1])

        async with self._cache_lock:
            now = time.monotonic()
            cached = self._cache
            if ttl > 0 and cached is not None and cached[0] > now:
                return list(cached[1])

            backend_tools = await self._backend_pool.list_tools()

            tools = self._adapt_catalog(backend_tools)
            tools.extend(self._catalog_tools(tools))
            tools.append(self._vocabulary_tool())
            self._validate_public_catalog(tools)
            if ttl > 0:
                self._cache = (now + ttl, tools)
            return list(tools)

    def _adapt_catalog(self, backend_tools: Sequence[McpTool]) -> list[Tool]:
        adapted: list[Tool] = []
        owners: dict[str, str] = {}
        aliases = {
            backend_tool.name: analysis_tool_name(backend_tool.name)
            for backend_tool in backend_tools
        }
        for backend_tool in backend_tools:
            if (
                backend_tool.name in {"search_tools", "check_tools"}
                or backend_tool.name.startswith("artifact_stage_")
                or backend_tool.name.startswith("artifact_file_")
            ):
                continue
            alias = analysis_tool_name(backend_tool.name)
            owner = owners.get(alias)
            if owner is not None and owner != backend_tool.name:
                raise AnalysisProviderError(
                    f"analysis tool alias collision: {owner!r} and "
                    f"{backend_tool.name!r} -> {alias!r}"
                )
            owners[alias] = backend_tool.name
            adapted.append(self._adapt_tool(backend_tool, alias, aliases))
        return adapted

    @staticmethod
    def _catalog_tools(public_tools: list[Tool]) -> list[Tool]:
        async def search_tools(query: str, limit: int = 15) -> AnalysisToolSearch:
            return search_catalog(public_tools, query, limit)

        async def check_tools(tools: str) -> AnalysisToolCheck:
            return check_catalog(public_tools, tools)

        search_tool = FunctionTool.from_function(
            search_tools,
            name="search_tools",
            title="Search Analysis Tools",
            description=(
                "Search the currently published Analysis tool catalog by public semantic "
                "name, title, or description. Results contain only callable public names."
            ),
        )
        check_tool = FunctionTool.from_function(
            check_tools,
            name="check_tools",
            title="Check Analysis Tools",
            description=(
                "Check whether public Analysis tool names are callable. Only names from the "
                "published Analysis catalog are accepted."
            ),
        )
        return [search_tool, check_tool]

    @staticmethod
    def _vocabulary_tool() -> Tool:
        async def get_analysis_vocabulary() -> AnalysisVocabulary:
            return analysis_vocabulary()

        return FunctionTool.from_function(
            get_analysis_vocabulary,
            name="get_analysis_vocabulary",
            title="Analysis Vocabulary",
            description=(
                "Return the canonical public terminology for this analysis workspace. "
                "Use these terms consistently when selecting tools and interpreting results."
            ),
        )

    @staticmethod
    def _validate_public_catalog(tools: Sequence[Tool]) -> None:
        violations: list[str] = []
        for tool in tools:
            public_metadata = {
                "name": tool.name,
                "title": tool.title,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            if not (tool.description or "").strip():
                violations.append(f"{tool.name}: missing public description")
            encoded = json.dumps(public_metadata, ensure_ascii=False, default=str)
            leaked = analysis_surface_violations(encoded)
            if leaked:
                violations.append(f"{tool.name}: {', '.join(leaked)}")
        if violations:
            raise AnalysisProviderError(
                "analysis public vocabulary leak: " + "; ".join(violations[:12])
            )

    def _adapt_tool(
        self,
        backend_tool: McpTool,
        analysis_name: str,
        aliases: dict[str, str] | None = None,
    ) -> Tool:
        ghidra_name = backend_tool.name
        exposed_tool = analysis_schema(backend_tool)
        exposed_tool.input_schema["title"] = f"{analysis_name}Arguments"
        argument_aliases = tool_alias(backend_tool).argument_aliases
        if argument_aliases:
            exposed_tool = _rewrite_catalog_references(exposed_tool, argument_aliases)
        if aliases:
            exposed_tool = _rewrite_catalog_references(exposed_tool, aliases)

        async def invoke(**arguments: object) -> CallToolResult | None:
            canonical = normalize_arguments(
                backend_tool,
                CallToolRequestParams(name=ghidra_name, arguments=arguments),
            )
            result = await self._backend_pool.call_tool(canonical)
            return decode_call_result(result)

        description = analysis_text(backend_tool.description or "").strip()
        title = backend_tool.title
        if not description:
            description = "Run the " + analysis_name.replace("_", " ") + " analysis operation."
        if argument_aliases:
            description = _rewrite_catalog_text(description, argument_aliases)
            if title:
                title = _rewrite_catalog_text(analysis_text(title), argument_aliases)
        if aliases:
            description = _rewrite_catalog_text(description, aliases)
            if title:
                title = _rewrite_catalog_text(analysis_text(title), aliases)
        metadata = Tool(
            name=analysis_name,
            title=analysis_text(title) if title else None,
            description=description,
            parameters=exposed_tool.input_schema,
            output_schema=deepcopy(_OUTPUT_SCHEMA),
        )
        adapted = Tool.from_tool(
            metadata, transform_fn=invoke, output_schema=metadata.output_schema
        )
        return adapted.model_copy(update={"parameters": exposed_tool.input_schema})
