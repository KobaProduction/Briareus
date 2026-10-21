"""Node Terminal: trusted supervisor and unprivileged existing tool process."""
import asyncio
import os
import socket
import stat
import time
from copy import deepcopy
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools import Tool, ToolResult
from mcp.types import CallToolResult
from pydantic import PrivateAttr

from hand_runtime.node_boundary import EffectBoundary
from hand_runtime.process_lease import ProcessLease
from node_protocol import Deployment
from node_protocol.effect import EffectVerifier, NodeEffectPermit
from node_protocol.terminal import TOOLS
from modules.terminal.tools import register_terminal_tools
from .worker_server import TerminalSupervisor, WorkerCall, require_supervisor_isolation
from .network_guard import read_attestation


class NodeTerminalTool(Tool):
    _supervisor: TerminalSupervisor = PrivateAttr()
    _network_check: object = PrivateAttr(default=None)

    async def run(self, arguments):
        permit = get_http_request().scope.get("briareus.node_effect")
        if (not isinstance(permit, NodeEffectPermit) or permit.module != "terminal"
            or permit.tool != self.name or permit.method != "tools/call" or permit.expires_at <= time.time()):
            raise ToolError("TERMINAL_CURRENT_AUTHORITY_REQUIRED")
        supervisor = self._supervisor
        claims = {"actor_uuid": str(permit.actor_uuid), "session_uuid": str(permit.agent_session_uuid),
                  "operation_uuid": str(permit.request_uuid)}
        try:
            if self._network_check is not None:
                self._network_check()
            await supervisor.grant_node(permit)
            from hand_runtime.runtime_policy import runtime_policy
            async with asyncio.timeout(runtime_policy().execution_timeout_seconds):
                reply = await supervisor.execute(WorkerCall(permit=get_http_request().headers["x-briareus-node-permit"],
                    tool=self.name, arguments=arguments), claims)
            if "result" not in reply or permit.expires_at <= time.time():
                raise ValueError("Terminal outcome unavailable")
            return ToolResult.from_mcp_result(CallToolResult.model_validate(reply["result"]))
        except asyncio.CancelledError:
            await supervisor.interrupt_node(permit)
            raise
        except (OSError, ValueError, KeyError, TimeoutError):
            await supervisor.interrupt_node(permit)
            raise ToolError("TERMINAL_OUTCOME_UNAVAILABLE") from None


def create_app(spec):
    if spec.release.module != "terminal" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved isolated Terminal contract required")
    network_facts = read_attestation(spec)
    require_supervisor_isolation(network_facts)
    verifier = EffectVerifier(spec)
    supervisor = TerminalSupervisor(spec.project_uuid, None, Path("/var/lib/terminal-supervisor"),
        execution_uid=1000, workspace_root="/project-data", prewarm=True, process_lease=ProcessLease(1000),
        network_facts=network_facts)
    template, mcp = FastMCP("terminal-metadata"), FastMCP("briareus-node-terminal")
    # Preserve the original tools, signatures, descriptions and annotations.
    # These metadata closures are never executed in the privileged supervisor.
    register_terminal_tools(template, None)
    app = mcp.http_app(path="/mcp", stateless_http=True, json_response=True,
        host_origin_protection=True, allowed_hosts=[f"{spec.container_name}.terminal", "localhost"])
    app.state.terminal_supervisor = supervisor
    sdk_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(current):
        watchdog = None
        try:
            metadata = await template.list_tools()
            if {tool.name for tool in metadata} != TOOLS:
                raise ValueError("Terminal tool catalogue differs from authority contract")
            for tool in metadata:
                parameters = deepcopy(tool.parameters)
                bounded = {"job_read": ("wait_seconds", 0),
                           "job_wait": ("timeout_seconds", 3)}.get(tool.name)
                if bounded:
                    field, default = bounded
                    parameters["properties"][field].update(default=default, minimum=0, maximum=3)
                proxy = NodeTerminalTool(name=tool.name, title=tool.title, description=tool.description,
                    parameters=parameters, output_schema=tool.output_schema, annotations=tool.annotations)
                proxy._supervisor = supervisor
                if network_facts is not None:
                    def check_network():
                        if read_attestation(spec) != network_facts:
                            raise ValueError("Terminal network placement changed")
                    proxy._network_check = check_network
                mcp.add_tool(proxy)
            await supervisor.warmup()
            watchdog = asyncio.create_task(supervisor.watchdog())
            async with sdk_lifespan(current) as state:
                async with Client(mcp, timeout=120) as client:
                    await client.list_tools()
                yield state
        finally:
            if watchdog is not None:
                watchdog.cancel()
                with suppress(asyncio.CancelledError):
                    await watchdog
            await supervisor.close()

    app.router.lifespan_context = lifespan
    return EffectBoundary(app, verifier, code="TERMINAL_CURRENT_AUTHORITY_REQUIRED",
        ready=lambda: supervisor.child_ready and supervisor.child is not None and supervisor.child.returncode is None)


def main():
    import uvicorn
    spec = Deployment.model_validate_json(os.environ["BRIAREUS_DEPLOYMENT"])
    os.umask(0o077)
    path = "/terminal-link/mcp.sock"
    parent = os.lstat("/terminal-link")
    if not stat.S_ISDIR(parent.st_mode) or (parent.st_uid, stat.S_IMODE(parent.st_mode)) != (0, 0o700):
        raise ValueError("Private rootless Terminal socket directory required")
    try:
        previous = os.lstat(path)
    except FileNotFoundError:
        previous = None
    if previous is not None:
        if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid != os.getuid():
            raise ValueError("Foreign Terminal socket")
        os.unlink(path)
    listener = socket.socket(socket.AF_UNIX)
    try:
        listener.bind(path)
        os.chmod(path, 0o600)
        listener.listen(32)
        uvicorn.Server(uvicorn.Config(create_app(spec), access_log=False, proxy_headers=False,
            timeout_graceful_shutdown=3)).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
