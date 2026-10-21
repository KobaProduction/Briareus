"""One authenticated SDK adapter for independently packaged Node MCP Hands.

Original tools supply their metadata; only the injected private executor runs
an effect. HTTP/browser clients cannot supply their own executor or settings.
"""
import asyncio
import hashlib
import inspect
import logging
from uuid import uuid4
import os
import socket
import stat
import time
from contextlib import AsyncExitStack, asynccontextmanager

from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools import Tool, ToolResult
from mcp.types import CallToolResult
from pydantic import PrivateAttr

from node_protocol import Deployment
from node_protocol.control import canonical
from node_protocol.effect import EffectVerifier, NodeEffectPermit
from .node_boundary import EffectBoundary
from .errors import NodePreparing


def invocation_context():
    request = get_http_request()
    permit = request.scope.get("briareus.node_effect")
    if not isinstance(permit,NodeEffectPermit) or permit.expires_at<=time.time():
        raise ValueError("Current private invocation authority required")
    return request.scope.get("briareus.invocation_context", {})


class NodeDelegatedTool(Tool):
    _execute = PrivateAttr()
    _module = PrivateAttr()

    async def run(self, arguments):
        permit = get_http_request().scope.get("briareus.node_effect")
        if (not isinstance(permit,NodeEffectPermit) or permit.module!=self._module
            or permit.method!="tools/call" or permit.tool!=self.name
            or permit.expires_at<=time.time()
            or permit.arguments_digest!=hashlib.sha256(canonical(arguments)).hexdigest()):
            raise ToolError("CURRENT_NODE_EFFECT_REQUIRED")
        try:
            from .runtime_policy import runtime_policy
            async with asyncio.timeout(runtime_policy().execution_timeout_seconds):
                result = await self._execute(self.name,arguments,permit)
            if permit.expires_at<=time.time():
                raise ValueError("Execution authority expired")
            if isinstance(result,ToolResult):
                return result
            return ToolResult.from_mcp_result(CallToolResult.model_validate(result))
        except NodePreparing:
            raise ToolError("NODE_PREPARING") from None
        except Exception as error:
            incident=uuid4().hex
            logging.getLogger(__name__).error("Node effect failed incident=%s module=%s exception=%s",incident,self._module,type(error).__name__)
            # Provider exceptions may contain credentials/URLs. They must not
            # become public SDK tracebacks or agent-visible error strings.
            raise ToolError("NODE_EFFECT_REJECTED_OR_UNAVAILABLE incident="+incident) from None


def create_node_app(spec, *, register_tools, execute, lifespan=None, ready=lambda:True):
    verifier = EffectVerifier(spec)
    template = FastMCP("node-source-"+spec.release.module)
    mcp = FastMCP("briareus-node-"+spec.release.module)
    app = mcp.http_app(path="/mcp",stateless_http=True,json_response=True,
        host_origin_protection=True,allowed_hosts=[
            spec.container_name+"."+spec.release.module,
            spec.container_name+":"+str(spec.release.port),"localhost"])
    sdk_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def application_lifespan(current):
        async with AsyncExitStack() as stack:
            # Dynamic source proxies need their isolated child's metadata first.
            if lifespan is not None:
                await stack.enter_async_context(lifespan(current))
            registration = register_tools(template)
            if inspect.isawaitable(registration):
                await registration
            tools = await template.list_tools()
            names = [item.name for item in tools]
            if not names or len(names)>512 or len(set(names))!=len(names):
                raise ValueError("A bounded unique original tool catalogue is required")
            for original in tools:
                proxy = NodeDelegatedTool(name=original.name,title=original.title,
                    description=original.description,parameters=original.parameters,
                    output_schema=original.output_schema,annotations=original.annotations,
                    meta=original.meta,icons=original.icons)
                proxy._module, proxy._execute = spec.release.module, execute
                mcp.add_tool(proxy)
            current.state.node_tool_names = tuple(names)
            state = await stack.enter_async_context(sdk_lifespan(current))
            async with Client(mcp,timeout=120) as metadata:
                await metadata.list_tools()
            yield state

    app.router.lifespan_context = application_lifespan
    app.state.node_spec = spec
    return EffectBoundary(app,verifier,code=spec.release.module.upper()+"_CURRENT_AUTHORITY_REQUIRED",ready=ready)


def run_node_app(create_app, module):
    """Fixed Unix ingress for a trusted supervisor in its rootless PID namespace."""
    import uvicorn
    from node_protocol.module_effects import MODULES
    if module not in MODULES:
        raise ValueError("Approved MCP module required")
    spec = Deployment.model_validate_json(os.environ["BRIAREUS_DEPLOYMENT"])
    if spec.release.module!=module:
        raise ValueError("Exact deployment module required")
    facts = dict(line.split(":",1) for line in open("/proc/self/status") if ":" in line)
    uid_map = open("/proc/self/uid_map").read().splitlines()
    if (os.geteuid()!=0 or facts["NoNewPrivs"].strip()!="1"
        or int(facts["CapEff"].strip(),16)!=(1<<5|1<<6|1<<7)
        or not os.statvfs("/").f_flag & os.ST_RDONLY
        or not uid_map or int(uid_map[0].split()[1])==0):
        raise ValueError("Dedicated rootless supervisor placement required")
    directory = "/"+module+"-link"
    parent = os.lstat(directory)
    if not stat.S_ISDIR(parent.st_mode) or (parent.st_uid,stat.S_IMODE(parent.st_mode))!=(0,0o700):
        raise ValueError("Private supervisor socket directory required")
    path = directory+"/mcp.sock"
    try:
        previous = os.lstat(path)
    except FileNotFoundError:
        previous = None
    if previous is not None:
        if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid!=0:
            raise ValueError("Foreign supervisor socket")
        os.unlink(path)
    os.umask(0o077)
    listener = socket.socket(socket.AF_UNIX)
    try:
        listener.bind(path)
        os.chmod(path,0o600)
        listener.listen(32)
        uvicorn.Server(uvicorn.Config(create_app(spec),access_log=False,proxy_headers=False,
            timeout_graceful_shutdown=3)).run(sockets=[listener])
    finally:
        listener.close()
