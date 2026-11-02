"""Non-executable, source-derived contracts for independently packaged Hands.

Inspect decorators and annotations as syntax, without importing providers,
looking up credentials, instantiating runtime clients or granting tool access.
These declarations must not be mistaken for FastMCP's validated JSON Schema.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

type SourceDefault = str | int | float | bool | None


class SourceArgument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    annotation: str | None
    required: bool
    default: SourceDefault = None


class SourceTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    module: str
    title: str | None = None
    description: str | None = None
    arguments: list[SourceArgument]
    return_annotation: str | None
    source_annotation_ref: str | None = None


class SourceCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    hand: str
    source: Literal["packaged_tool_declarations"]
    interface_format: Literal["python_declaration_not_mcp_json_schema"]
    declared_tool_count: int
    declared_tools: list[SourceTool]
    mcp_transport: Literal["not_mounted", "resource_auth_staged", "diagnostic_only"]
    authorization: Literal["not_configured", "resource_verifier_configured_unaccepted"]
    execution: Literal["disabled", "owner_ports_injected_unaccepted"]


class _ToolDeclaration(NamedTuple):
    name: str
    title: str | None
    source_annotation_ref: str | None


def _is_tool_decorator(decorator: ast.expr) -> bool:
    return (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "tool"
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "mcp"
    )


def _declared_metadata(name: str, decorator: ast.Call) -> _ToolDeclaration:
    title, source_annotation_ref = None, None
    for keyword in decorator.keywords:
        if keyword.arg in {"name", "title"}:
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                if keyword.arg == "name":
                    name = keyword.value.value
                else:
                    title = keyword.value.value
        elif keyword.arg == "annotations" and isinstance(keyword.value, ast.Name):
            source_annotation_ref = keyword.value.id
    return _ToolDeclaration(name, title, source_annotation_ref)


def _tool_declaration(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> _ToolDeclaration | None:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call) and _is_tool_decorator(decorator):
            return _declared_metadata(node.name, decorator)
    return None


def _argument(name: str, annotation: ast.expr | None, default: ast.expr | None) -> SourceArgument:
    result = SourceArgument(
        name=name,
        annotation=ast.unparse(annotation) if annotation is not None else None,
        required=default is None,
    )
    if default is not None:
        try:
            value = ast.literal_eval(default)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return result
        if (value is None or isinstance(value, (str, int, float, bool))) and len(str(value)) <= 200:
            return result.model_copy(update={"default": value})
    return result


def _arguments(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[SourceArgument]:
    arguments = node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    default_start = len(positional) - len(arguments.defaults)
    parameters = [
        _argument(
            parameter.arg,
            parameter.annotation,
            arguments.defaults[index - default_start] if index >= default_start else None,
        )
        for index, parameter in enumerate(positional)
    ]
    for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        parameters.append(_argument(parameter.arg, parameter.annotation, default))
    # FastMCP decorated tools in the checked source don't use *args/**kwargs;
    # those are not representable by a simple source argument list.
    if arguments.vararg or arguments.kwarg:
        raise ValueError(f"dynamic parameter list in MCP declaration: {node.name}")
    return parameters


def _source_tool(
    module: str, node: ast.FunctionDef | ast.AsyncFunctionDef, declaration: _ToolDeclaration
) -> SourceTool:
    tool = SourceTool(
        name=declaration.name,
        module=module,
        arguments=_arguments(node),
        return_annotation=ast.unparse(node.returns) if node.returns else None,
    )
    updates: dict[str, str] = {}
    if declaration.title is not None:
        updates["title"] = declaration.title
    docstring = ast.get_docstring(node, clean=True)
    if docstring:
        updates["description"] = docstring[:800]
    if declaration.source_annotation_ref is not None:
        updates["source_annotation_ref"] = declaration.source_annotation_ref
    return tool.model_copy(update=updates)


def _module_tools(source: Path, modules_root: Path) -> list[SourceTool]:
    module = "modules." + ".".join(source.relative_to(modules_root).with_suffix("").parts)
    parsed = ast.parse(source.read_text(encoding="utf-8"), filename=module)
    tools: list[SourceTool] = []
    for node in ast.walk(parsed):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            declaration = _tool_declaration(node)
            if declaration is not None:
                tools.append(_source_tool(module, node, declaration))
    return tools


def discover_source_tools(modules_root: Path) -> list[SourceTool]:
    """Read only declarations; never initialize tool registries or clients."""
    if not modules_root.is_dir():
        raise FileNotFoundError("Hand source tool package is absent")
    result: list[SourceTool] = []
    for source in sorted(modules_root.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        result.extend(_module_tools(source, modules_root))
    return sorted(result, key=lambda item: (item.module, item.name))


def source_capabilities(hand: str, modules_root: Path) -> SourceCapabilities:
    """Private v1 source metadata; execution and auth readiness remain false."""
    if not hand or not hand.replace("-", "").isidentifier():
        raise ValueError("invalid Hand identifier")
    tools = discover_source_tools(modules_root)
    return SourceCapabilities(
        schema_version=1,
        hand=hand,
        source="packaged_tool_declarations",
        interface_format="python_declaration_not_mcp_json_schema",
        declared_tool_count=len(tools),
        declared_tools=tools,
        mcp_transport="not_mounted",
        authorization="not_configured",
        execution="disabled",
    )
