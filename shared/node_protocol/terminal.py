"""Bounded Terminal MCP interpretation, shared by authority and executor."""

import hashlib
import json
import math
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt

from .control import canonical
from .domain.mcp_request import McpRequestFacts
from .json_boundary import request_facts, require_json_object

TOOLS = frozenset(
    {
        "terminal_status",
        "workspace_list",
        "workspace_create",
        "workspace_info",
        "workspace_delete",
        "terminal_exec",
        "job_start",
        "job_status",
        "job_list",
        "job_delete",
        "job_cleanup",
        "job_read",
        "job_write",
        "job_resize",
        "job_wait",
        "job_cancel",
    }
)


def workspace_resource(node: UUID | str, project: UUID | str, workspace: UUID | str) -> str:
    digest = hashlib.sha256(
        b"briareus:terminal-workspace\0"
        + canonical(
            {"node_uuid": str(node), "project_uuid": str(project), "workspace_uuid": str(workspace)}
        )
    ).hexdigest()
    return "project-terminal:" + str(project) + ":" + digest


class _ExecutionWindow(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    timeout_seconds: StrictInt | StrictFloat | None = None

    def require_positive(self) -> None:
        timeout = self.timeout_seconds
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("Execution timeout must be positive and finite or null")


class _ReadWindow(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    wait_seconds: StrictInt | StrictFloat = Field(default=0, ge=0, le=3)


class _WaitWindow(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    timeout_seconds: StrictInt | StrictFloat = Field(default=3, ge=0, le=3)


def _validate_wait(tool: str, arguments: object) -> None:
    if tool == "terminal_exec":
        _ExecutionWindow.model_validate(arguments).require_positive()
    elif tool == "job_read":
        _ReadWindow.model_validate(arguments)
    elif tool == "job_wait":
        _WaitWindow.model_validate(arguments)


def parse_request(raw: bytes) -> McpRequestFacts:
    if not isinstance(raw, bytes):
        raise ValueError("Bounded Terminal request required")
    if not 0 < len(raw) <= 32768:
        raise ValueError("Bounded Terminal request required")
    require_json_object(raw)
    body: object = json.loads(raw)
    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or set(body) - {"jsonrpc", "id", "method", "params"}
        or ("id" in body and (type(body["id"]) not in {str, int} or len(str(body["id"])) > 128))
    ):
        raise ValueError("Single JSON-RPC request required")
    method = body.get("method")
    if method in {"initialize", "notifications/initialized", "ping", "tools/list"}:
        if not isinstance(body.get("params", {}), dict):
            raise ValueError("MCP parameters must be an object")
        return request_facts(method, None, {})
    params = body.get("params")
    if (
        method != "tools/call"
        or not isinstance(params, dict)
        or set(params) - {"name", "arguments", "_meta"}
        or params.get("name") not in TOOLS
    ):
        raise ValueError("Approved Terminal tool required")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict) or len(arguments) > 16:
        raise ValueError("Bounded Terminal arguments required")
    # Commands run as retained jobs. Only observation waits must fit the
    # independently verified request lease; they never cap process lifetime.
    _validate_wait(params["name"], arguments)
    return request_facts(method, params["name"], arguments)
