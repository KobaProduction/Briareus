"""Bounded MCP interpretation and isolated resource names shared by Core/Hands."""
import hashlib
import re

from .control import canonical
from .files import FileRequest, strict_json

MODULES = frozenset({"files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"})
RESOURCE_KINDS = {"files":"workspace_path", "terminal":"workspace", "web":"browser_session",
    "svc":"repository", "infrastructure":"application", "reverse":"analysis_project",
    "serena":"workspace"}
DEFAULT_ACTIONS = {"files":"files.read", "terminal":"terminal.execute", "web":"web.access",
    "svc":"integrations.use", "infrastructure":"integrations.use", "reverse":"analysis.import",
    "serena":"terminal.execute"}
TOOL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z", re.ASCII)


def effect_action(module, tool):
    if module == "files":
        from .files import READ_TOOLS, WRITE_TOOLS
        if tool in WRITE_TOOLS:
            return "files.write"
        if tool is not None and tool not in READ_TOOLS:
            raise ValueError("Unknown Files tool")
    if module == "infrastructure" and tool == "observability_application_variables":
        return "variables.use"
    return DEFAULT_ACTIONS[module]


def resource_id(module, node, project, storage):
    if module == "files":
        from .files import workspace_resource
        return workspace_resource(node, project, storage)
    if module == "terminal":
        from .terminal import workspace_resource
        return workspace_resource(node, project, storage)
    if module not in MODULES:
        raise ValueError("Unknown module resource")
    digest = hashlib.sha256(("briareus:"+module+"-storage\0").encode() + canonical({
        "node_uuid":str(node), "project_uuid":str(project), "storage_uuid":str(storage)})).hexdigest()
    return "project-"+module+":"+str(project)+":"+digest


def parse_request(module, raw):
    if module == "files":
        from .files import parse_request as parse_files
        return parse_files(raw)
    if module == "terminal":
        from .terminal import parse_request as parse_terminal
        return parse_terminal(raw)
    if module not in MODULES or not isinstance(raw, bytes) or not 0 < len(raw) <= 32768:
        raise ValueError("Bounded known MCP module required")
    body = strict_json(raw)
    if (not isinstance(body, dict) or body.get("jsonrpc") != "2.0"
        or set(body)-{"jsonrpc","id","method","params"}
        or "id" in body and (type(body["id"]) not in {str,int} or len(str(body["id"]))>128)):
        raise ValueError("Single JSON-RPC request required")
    method, params = body.get("method"), body.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("MCP parameters must be an object")
    if method in {"initialize","notifications/initialized","ping","tools/list"}:
        return FileRequest(method, None, {})
    if (method != "tools/call" or set(params)-{"name","arguments","_meta"}
        or not isinstance(params.get("name"),str) or not TOOL_NAME.fullmatch(params["name"])):
        raise ValueError("Named MCP tool required")
    arguments = params.get("arguments", {})
    if not isinstance(arguments,dict) or len(arguments)>64:
        raise ValueError("Bounded tool arguments required")
    # Core grants the exact name and resource; the pinned Hand's actual SDK
    # catalogue rejects unknown tools. Prefixes never confer authorization.
    return FileRequest(method, params["name"], arguments)
