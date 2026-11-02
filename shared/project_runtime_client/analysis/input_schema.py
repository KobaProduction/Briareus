"""Adapt native MCP schema metadata without inventing generic JSON data contracts."""

import json
from functools import lru_cache

from fastmcp.utilities.json_schema_type import json_schema_to_type
from mcp.types import CallToolRequestParams, Tool
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from pydantic_core import SchemaValidator

from .terminology import (
    _COLLAPSED_ACTION_SELECTOR_TOOLS,
    analysis_argument_name,
    analysis_text,
    analysis_tool_name,
)


class ParameterNaming(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    alias: str | None = Field(default=None, validation_alias="x-analysis-alias")

    @field_validator("alias", mode="before")
    @classmethod
    def explicit_alias(cls, value: object) -> str | None:
        return value.strip() or None if isinstance(value, str) else None


class ToolAlias(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ghidra_name: str
    analysis_name: str
    argument_aliases: dict[str, str]


def _parameter_names(tool: Tool) -> tuple[str, ...]:
    properties = tool.input_schema.get("properties")
    if not isinstance(properties, dict):
        return ()
    return tuple(str(name) for name, schema in properties.items() if isinstance(schema, dict))


def _argument_name(tool: Tool, name: str) -> str:
    naming = ParameterNaming.model_validate(tool.input_schema["properties"][name])
    return analysis_argument_name(name, naming.alias, tool.name)


def _normalize_default(tool: Tool, name: str) -> None:
    schema = tool.input_schema["properties"][name]
    value, kind = schema.get("default"), schema.get("type")
    if not isinstance(value, str) or not isinstance(kind, str):
        return
    if kind in {"integer", "number", "boolean"} and value == "":
        schema.pop("default", None)
        return
    try:
        if kind == "integer":
            schema["default"] = int(value)
        elif kind == "number":
            schema["default"] = float(value)
        elif kind == "boolean" and value.casefold() in {"true", "false"}:
            schema["default"] = value.casefold() == "true"
    except ValueError:
        # Invalid native defaults retain their original value, never a guessed coercion.
        return


def _normalized_backend(tool: Tool) -> Tool:
    normalized = tool.model_copy(deep=True)
    for name in _parameter_names(normalized):
        _normalize_default(normalized, name)
    return normalized


def tool_alias(tool: Tool) -> ToolAlias:
    return ToolAlias(
        ghidra_name=tool.name,
        analysis_name=analysis_tool_name(tool.name),
        argument_aliases={
            name: _argument_name(tool, name)
            for name in _parameter_names(tool)
            if _argument_name(tool, name) != name
        },
    )


def analysis_schema(tool: Tool) -> Tool:
    public = _normalized_backend(tool)
    properties = public.input_schema.get("properties")
    if not isinstance(properties, dict):
        return public
    source = tuple(properties.items())
    properties.clear()
    owners: dict[str, str] = {}
    for name, schema in source:
        if tool.name in _COLLAPSED_ACTION_SELECTOR_TOOLS and name == "address":
            continue
        alias = _argument_name(tool, name)
        if alias in owners and owners[alias] != name:
            raise ValueError("Analysis argument alias collision")
        owners[alias] = name
        properties[alias] = schema
        _translate_titles(public, alias)
    _translate_titles(public)
    _public_required(tool, public)
    return public


def _translate_titles(tool: Tool, parameter: str | None = None) -> None:
    schema = tool.input_schema if parameter is None else tool.input_schema["properties"][parameter]
    for field in ("title", "description"):
        if isinstance(schema.get(field), str):
            schema[field] = analysis_text(schema[field])


def _public_required(source: Tool, public: Tool) -> None:
    required = public.input_schema.get("required")
    if isinstance(required, list):
        names = set(_parameter_names(source))
        public.input_schema["required"] = [
            _argument_name(source, str(name))
            if str(name) in names
            else analysis_argument_name(str(name), tool_name=source.name)
            for name in required
        ]
    if source.name in _COLLAPSED_ACTION_SELECTOR_TOOLS:
        required = public.input_schema.setdefault("required", [])
        if isinstance(required, list) and "action" not in required:
            required.append("action")


@lru_cache(maxsize=512)
def _argument_validator(schema_key: str) -> SchemaValidator:
    schema: object = json.loads(schema_key)
    if not isinstance(schema, dict):
        raise ValueError("Native tool schema required")
    # FastMCP owns dynamic JSON Schema interpretation, including nested fields.
    # The resulting value is discarded; executable values remain in the SDK call.
    native_type = json_schema_to_type(schema)
    return SchemaValidator(TypeAdapter(native_type).core_schema)


def _bind_parameter(tool: Tool, call: CallToolRequestParams, name: str, *, required: bool) -> None:
    arguments = call.arguments
    if arguments is None:
        raise ValueError("SDK arguments must be initialized before binding")
    alias = _argument_name(tool, name)
    if not required:
        for candidate in {name, alias}:
            if arguments.get(candidate) is None:
                arguments.pop(candidate, None)
    if alias != name and alias in arguments:
        arguments[name] = arguments.pop(alias)
    default = tool.input_schema["properties"][name].get("default")
    if name not in arguments and default is not None:
        arguments[name] = default
    if (
        tool.input_schema["properties"][name].get("type") == "number"
        and type(arguments.get(name)) is int
    ):
        arguments[name] = float(arguments[name])


def normalize_arguments(tool: Tool, request: CallToolRequestParams) -> CallToolRequestParams:
    if request.name != tool.name:
        raise ValueError("Matching native analysis tool required")
    native = _normalized_backend(tool)
    normalized = request.model_copy(deep=True)
    normalized.arguments = normalized.arguments or {}
    names = tuple(sorted(_parameter_names(native)))
    required = native.input_schema.get("required", [])
    for name in names:
        _bind_parameter(native, normalized, name, required=name in required)
    arguments = normalized.arguments
    if set(arguments).difference(names):
        raise ValueError("Unexpected native analysis arguments")
    schema_key = json.dumps(native.input_schema, sort_keys=True, separators=(",", ":"))
    _argument_validator(schema_key).validate_json(
        json.dumps(arguments, allow_nan=False), strict=True
    )
    normalized.arguments = {name: arguments[name] for name in names if name in arguments}
    return normalized
