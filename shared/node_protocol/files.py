"""Files MCP request interpretation, shared by issuer and executor."""
import hashlib
import json
from dataclasses import dataclass

from .control import canonical

READ_TOOLS = frozenset({"file_status", "file_list", "file_info", "file_read", "file_hash"})
WRITE_TOOLS = frozenset({"file_write_text", "file_write", "file_ingest", "file_mkdir", "file_copy", "file_move", "file_delete"})
ARGUMENTS = {
    "file_status": set(), "file_list": {"path", "offset", "limit"},
    "file_info": {"path"}, "file_read": {"path", "offset", "length"}, "file_hash": {"path"},
    "file_write_text": {"path", "content", "overwrite", "create_parents"},
    "file_write": {"path", "data_base64", "offset", "truncate", "create_parents"},
    "file_ingest": {"file", "destination", "expected_size", "expected_sha256", "overwrite"},
    "file_mkdir": {"path", "parents"}, "file_copy": {"source", "destination", "overwrite"},
    "file_move": {"source", "destination", "overwrite"}, "file_delete": {"path", "recursive"},
}


def workspace_resource(node, project, workspace):
    digest=hashlib.sha256(b"briareus:project-workspace\0"+canonical(
        {"node_uuid":str(node),"project_uuid":str(project),"workspace_uuid":str(workspace)})).hexdigest()
    return "project-files:"+str(project)+":"+digest


def strict_json(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key]=value
        return result
    def invalid(value):
        raise ValueError("Non-finite JSON value")
    try:
        return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    except (ValueError,UnicodeError,RecursionError):
        raise ValueError("Invalid bounded JSON") from None


@dataclass(frozen=True)
class FileRequest:
    method: str
    tool: str | None
    arguments: dict


def parse_request(raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=32768:
        raise ValueError("Bounded Files request required")
    body=strict_json(raw)
    if not isinstance(body,dict) or body.get("jsonrpc")!="2.0" or set(body)-{"jsonrpc","id","method","params"}:
        raise ValueError("Single JSON-RPC request required")
    if "id" in body and (type(body["id"]) not in {str,int} or len(str(body["id"]))>128):
        raise ValueError("Bounded JSON-RPC identity required")
    method=body.get("method")
    if method in {"initialize","notifications/initialized","ping","tools/list"}:
        if not isinstance(body.get("params",{}),dict):
            raise ValueError("MCP parameters must be an object")
        return FileRequest(method,None,{})
    if method!="tools/call":
        raise ValueError("Unsupported Files MCP method")
    params=body.get("params")
    if not isinstance(params,dict) or set(params)-{"name","arguments","_meta"} or params.get("name") not in READ_TOOLS | WRITE_TOOLS:
        raise ValueError("Approved Files tool required")
    tool=params["name"]
    args=params.get("arguments",{})
    if not isinstance(args,dict) or set(args)-ARGUMENTS[tool]:
        raise ValueError("Exact Files arguments required")
    for key in {"path", "source", "destination", "content", "data_base64", "expected_sha256"} & args.keys():
        if not isinstance(args[key],str):
            raise ValueError("String Files argument required")
    for key in {"overwrite", "create_parents", "truncate", "parents", "recursive"} & args.keys():
        if type(args[key]) is not bool:
            raise ValueError("Boolean Files argument required")
    for key in {"offset", "length", "limit", "expected_size"} & args.keys():
        if key=="expected_size" and args[key] is None:
            continue
        if type(args[key]) is not int or not 0<=args[key]<2**63:
            raise ValueError("Bounded Files integer required")
    if tool=="file_read" and not 1<=args.get("length",1024*1024)<=16*1024*1024:
        raise ValueError("Bounded read arguments required")
    # The immutable Hand's original schema validates required fields and the
    # attachment object. Core grants this exact tool plus canonical arguments;
    # it does not reinterpret or execute their content.
    return FileRequest(method,tool,args)
