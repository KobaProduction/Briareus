"""Bounded Terminal MCP interpretation, shared by authority and executor."""
import hashlib
import math

from .control import canonical
from .files import FileRequest, strict_json

TOOLS = frozenset({"terminal_status", "workspace_list", "workspace_create", "workspace_info",
    "workspace_delete", "terminal_exec", "job_start", "job_status", "job_list", "job_delete",
    "job_cleanup", "job_read", "job_write", "job_resize", "job_wait", "job_cancel"})


def workspace_resource(node, project, workspace):
    digest = hashlib.sha256(b"briareus:terminal-workspace\0" + canonical({
        "node_uuid": str(node), "project_uuid": str(project), "workspace_uuid": str(workspace)})).hexdigest()
    return "project-terminal:" + str(project) + ":" + digest


def parse_request(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 32768:
        raise ValueError("Bounded Terminal request required")
    body = strict_json(raw)
    if (not isinstance(body, dict) or body.get("jsonrpc") != "2.0"
        or set(body) - {"jsonrpc", "id", "method", "params"}
        or "id" in body and (type(body["id"]) not in {str, int} or len(str(body["id"])) > 128)):
        raise ValueError("Single JSON-RPC request required")
    method = body.get("method")
    if method in {"initialize", "notifications/initialized", "ping", "tools/list"}:
        if not isinstance(body.get("params", {}), dict):
            raise ValueError("MCP parameters must be an object")
        return FileRequest(method, None, {})
    params = body.get("params")
    if (method != "tools/call" or not isinstance(params, dict)
        or set(params) - {"name", "arguments", "_meta"} or params.get("name") not in TOOLS):
        raise ValueError("Approved Terminal tool required")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict) or len(arguments) > 16:
        raise ValueError("Bounded Terminal arguments required")
    # Commands run as retained jobs. Only observation waits must fit the
    # independently verified request lease; they never cap process lifetime.
    if params["name"] == "terminal_exec":
        timeout = arguments.get("timeout_seconds")
        if timeout is not None and (type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("Execution timeout must be positive and finite or null")
    bounded = {"job_read": ("wait_seconds", 0),
               "job_wait": ("timeout_seconds", 3)}.get(params["name"])
    if bounded:
        value = arguments.get(*bounded)
        if type(value) not in {int, float} or not 0 <= value <= 3:
            raise ValueError("Use a job for work longer than the request lease")
    return FileRequest(method, params["name"], arguments)
