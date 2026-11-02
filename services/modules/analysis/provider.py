"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

import asyncio as asyncio
import json as json
import re as re
import time as time
from collections.abc import Sequence as Sequence
from copy import deepcopy as deepcopy

from fastmcp import Client as Client
from fastmcp.client.transports import StreamableHttpTransport as StreamableHttpTransport
from fastmcp.server.providers import Provider as Provider
from fastmcp.tools import FunctionTool as FunctionTool
from fastmcp.tools import Tool as Tool
from fastmcp.utilities.components import FastMCPComponent as FastMCPComponent
from mcp.types import CallToolRequestParams as CallToolRequestParams
from mcp.types import CallToolResult as CallToolResult

from common.mcp_client_pool import PersistentMcpClientPool as PersistentMcpClientPool
from common.settings import AnalysisSettings as AnalysisSettings
from hand_runtime.provider_schemas import (
    WRAPPED_PROVIDER_RESULT_SCHEMA as WRAPPED_PROVIDER_RESULT_SCHEMA,
)
from project_runtime_client.analysis.provider import _OUTPUT_SCHEMA as _OUTPUT_SCHEMA
from project_runtime_client.analysis.provider import AnalysisProviderError as AnalysisProviderError
from project_runtime_client.analysis.provider import AnalysisToolProvider as AnalysisToolProvider
from project_runtime_client.analysis.provider import (
    _rewrite_catalog_references as _rewrite_catalog_references,
)
from project_runtime_client.analysis.provider import _rewrite_catalog_text as _rewrite_catalog_text
from project_runtime_client.analysis.provider import (
    _rewrite_schema_fields as _rewrite_schema_fields,
)
from project_runtime_client.analysis.provider import _rewrite_schema_items as _rewrite_schema_items
from service_runtime.mcp_http import mcp_http_client as mcp_http_client

from .catalog_queries import check_catalog as check_catalog
from .catalog_queries import search_catalog as search_catalog
from .catalog_views import AnalysisToolCheck as AnalysisToolCheck
from .catalog_views import AnalysisToolSearch as AnalysisToolSearch
from .catalog_views import AnalysisVocabulary as AnalysisVocabulary
from .input_schema import analysis_schema as analysis_schema
from .input_schema import normalize_arguments as normalize_arguments
from .input_schema import tool_alias as tool_alias
from .result import decode_call_result as decode_call_result
from .terminology import analysis_surface_violations as analysis_surface_violations
from .terminology import analysis_text as analysis_text
from .terminology import analysis_tool_name as analysis_tool_name
from .terminology import analysis_vocabulary as analysis_vocabulary
