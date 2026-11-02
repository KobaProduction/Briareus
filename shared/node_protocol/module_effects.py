"""Bounded MCP interpretation and isolated resource names shared by Core/Hands."""

import hashlib
import json
import re
from uuid import UUID

from .control import canonical
from .domain.mcp_request import McpRequestFacts
from .json_boundary import request_facts, require_json_object

MODULES = frozenset({"files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"})
RESOURCE_KINDS = {
    "files": "workspace_path",
    "terminal": "workspace",
    "web": "browser_session",
    "svc": "repository",
    "infrastructure": "application",
    "reverse": "analysis_project",
    "serena": "workspace",
}
DEFAULT_ACTIONS = {
    "files": "files.read",
    "terminal": "terminal.execute",
    "web": "web.access",
    "svc": "integrations.use",
    "infrastructure": "integrations.use",
    "reverse": "analysis.import",
    "serena": "terminal.execute",
}
TOOL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z", re.ASCII)


def effect_action(module: str, tool: str | None) -> str:
    if module == "files":
        from .files import READ_TOOLS, WRITE_TOOLS

        if tool in WRITE_TOOLS:
            return "files.write"
        if tool is not None and tool not in READ_TOOLS:
            raise ValueError("Unknown Files tool")
    if module == "infrastructure" and tool == "observability_application_variables":
        return "variables.use"
    return DEFAULT_ACTIONS[module]


def resource_id(module: str, node: UUID | str, project: UUID | str, storage: UUID | str) -> str:
    if module == "files":
        from .files import workspace_resource as files_resource

        return files_resource(node, project, storage)
    if module == "terminal":
        from .terminal import workspace_resource as terminal_resource

        return terminal_resource(node, project, storage)
    if module not in MODULES:
        raise ValueError("Unknown module resource")
    digest = hashlib.sha256(
        ("briareus:" + module + "-storage\0").encode()
        + canonical(
            {"node_uuid": str(node), "project_uuid": str(project), "storage_uuid": str(storage)}
        )
    ).hexdigest()
    return "project-" + module + ":" + str(project) + ":" + digest


def _valid_request_identity(value: object) -> bool:
    return type(value) in {str, int} and len(str(value)) <= 128


def parse_request(module: str, raw: bytes) -> McpRequestFacts:
    if module == "files":
        from .files import parse_request as parse_files

        return parse_files(raw)
    if module == "terminal":
        from .terminal import parse_request as parse_terminal

        return parse_terminal(raw)
    if not isinstance(raw, bytes):
        raise ValueError("Bounded known MCP module required")
    if module not in MODULES or not 0 < len(raw) <= 32768:
        raise ValueError("Bounded known MCP module required")
    require_json_object(raw)
    body: object = json.loads(raw)
    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or set(body) - {"jsonrpc", "id", "method", "params"}
        or ("id" in body and not _valid_request_identity(body["id"]))
    ):
        raise ValueError("Single JSON-RPC request required")
    method, params = body.get("method"), body.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("MCP parameters must be an object")
    if method in {"initialize", "notifications/initialized", "ping", "tools/list"}:
        return request_facts(method, None, {})
    if (
        method != "tools/call"
        or set(params) - {"name", "arguments", "_meta"}
        or not isinstance(params.get("name"), str)
        or not TOOL_NAME.fullmatch(params["name"])
    ):
        raise ValueError("Named MCP tool required")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict) or len(arguments) > 64:
        raise ValueError("Bounded tool arguments required")
    # Core grants the exact name and resource; the pinned Hand's actual SDK
    # catalogue rejects unknown tools. Prefixes never confer authorization.
    return request_facts(method, params["name"], arguments)
