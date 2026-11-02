"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

import json as json
from functools import lru_cache as lru_cache

from fastmcp.utilities.json_schema_type import json_schema_to_type as json_schema_to_type
from mcp.types import CallToolRequestParams as CallToolRequestParams
from mcp.types import Tool as Tool
from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict
from pydantic import Field as Field
from pydantic import TypeAdapter as TypeAdapter
from pydantic import field_validator as field_validator
from pydantic_core import SchemaValidator as SchemaValidator

from project_runtime_client.analysis.input_schema import ParameterNaming as ParameterNaming
from project_runtime_client.analysis.input_schema import ToolAlias as ToolAlias
from project_runtime_client.analysis.input_schema import _argument_name as _argument_name
from project_runtime_client.analysis.input_schema import _argument_validator as _argument_validator
from project_runtime_client.analysis.input_schema import _bind_parameter as _bind_parameter
from project_runtime_client.analysis.input_schema import _normalize_default as _normalize_default
from project_runtime_client.analysis.input_schema import _normalized_backend as _normalized_backend
from project_runtime_client.analysis.input_schema import _parameter_names as _parameter_names
from project_runtime_client.analysis.input_schema import _public_required as _public_required
from project_runtime_client.analysis.input_schema import _translate_titles as _translate_titles
from project_runtime_client.analysis.input_schema import analysis_schema as analysis_schema
from project_runtime_client.analysis.input_schema import normalize_arguments as normalize_arguments
from project_runtime_client.analysis.input_schema import tool_alias as tool_alias

from .terminology import _COLLAPSED_ACTION_SELECTOR_TOOLS as _COLLAPSED_ACTION_SELECTOR_TOOLS
from .terminology import analysis_argument_name as analysis_argument_name
from .terminology import analysis_text as analysis_text
from .terminology import analysis_tool_name as analysis_tool_name
