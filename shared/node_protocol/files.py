"""Files MCP request interpretation, shared by issuer and executor."""

import hashlib
import json
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from pydantic_core import MISSING

from .control import canonical
from .domain.mcp_request import McpRequestFacts
from .json_boundary import request_facts, require_json_object

READ_TOOLS = frozenset({"file_status", "file_list", "file_info", "file_read", "file_hash"})
WRITE_TOOLS = frozenset(
    {
        "file_write_text",
        "file_write",
        "file_ingest",
        "file_mkdir",
        "file_copy",
        "file_move",
        "file_delete",
    }
)
ARGUMENTS = {
    "file_status": set(),
    "file_list": {"path", "offset", "limit"},
    "file_info": {"path"},
    "file_read": {"path", "offset", "length"},
    "file_hash": {"path"},
    "file_write_text": {"path", "content", "overwrite", "create_parents"},
    "file_write": {"path", "data_base64", "offset", "truncate", "create_parents"},
    "file_ingest": {"file", "destination", "expected_size", "expected_sha256", "overwrite"},
    "file_mkdir": {"path", "parents"},
    "file_copy": {"source", "destination", "overwrite"},
    "file_move": {"source", "destination", "overwrite"},
    "file_delete": {"path", "recursive"},
}


def workspace_resource(node: UUID | str, project: UUID | str, workspace: UUID | str) -> str:
    digest = hashlib.sha256(
        b"briareus:project-workspace\0"
        + canonical(
            {"node_uuid": str(node), "project_uuid": str(project), "workspace_uuid": str(workspace)}
        )
    ).hexdigest()
    return "project-files:" + str(project) + ":" + digest


type _FileInteger = Annotated[int, Field(strict=True, ge=0, lt=2**63)]


class _FileArgumentTypes(BaseModel):
    # Exact key sets are checked against ARGUMENTS before this projection.
    # The immutable Hand validates attachment content and required fields.
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    path: StrictStr | MISSING = MISSING
    source: StrictStr | MISSING = MISSING
    destination: StrictStr | MISSING = MISSING
    content: StrictStr | MISSING = MISSING
    data_base64: StrictStr | MISSING = MISSING
    expected_sha256: StrictStr | MISSING = MISSING
    overwrite: StrictBool | MISSING = MISSING
    create_parents: StrictBool | MISSING = MISSING
    truncate: StrictBool | MISSING = MISSING
    parents: StrictBool | MISSING = MISSING
    recursive: StrictBool | MISSING = MISSING
    offset: _FileInteger | MISSING = MISSING
    length: _FileInteger | MISSING = MISSING
    limit: _FileInteger | MISSING = MISSING
    expected_size: _FileInteger | MISSING | None = MISSING

    def require_read_window(self, tool: str) -> None:
        if tool != "file_read":
            return
        length = 1024 * 1024 if self.length is MISSING else self.length
        if not 1 <= length <= 16 * 1024 * 1024:
            raise ValueError("Bounded read arguments required")


def parse_request(raw: bytes) -> McpRequestFacts:
    if not isinstance(raw, bytes):
        raise ValueError("Bounded Files request required")
    if not 0 < len(raw) <= 32768:
        raise ValueError("Bounded Files request required")
    require_json_object(raw)
    body: object = json.loads(raw)
    if (
        not isinstance(body, dict)
        or body.get("jsonrpc") != "2.0"
        or set(body) - {"jsonrpc", "id", "method", "params"}
    ):
        raise ValueError("Single JSON-RPC request required")
    if "id" in body and (type(body["id"]) not in {str, int} or len(str(body["id"])) > 128):
        raise ValueError("Bounded JSON-RPC identity required")
    method = body.get("method")
    if method in {"initialize", "notifications/initialized", "ping", "tools/list"}:
        if not isinstance(body.get("params", {}), dict):
            raise ValueError("MCP parameters must be an object")
        return request_facts(method, None, {})
    if method != "tools/call":
        raise ValueError("Unsupported Files MCP method")
    params = body.get("params")
    if (
        not isinstance(params, dict)
        or set(params) - {"name", "arguments", "_meta"}
        or params.get("name") not in READ_TOOLS | WRITE_TOOLS
    ):
        raise ValueError("Approved Files tool required")
    tool = params["name"]
    args = params.get("arguments", {})
    if not isinstance(args, dict) or set(args) - ARGUMENTS[tool]:
        raise ValueError("Exact Files arguments required")
    arguments = _FileArgumentTypes.model_validate(args)
    arguments.require_read_window(tool)
    # The immutable Hand's original schema validates required fields and the
    # attachment object. Core grants this exact tool plus canonical arguments;
    # it does not reinterpret or execute their content.
    return request_facts(method, tool, args)
