"""Node Terminal: trusted supervisor and unprivileged existing tool process."""

import os
import socket
import stat
from pathlib import Path

from fastmcp import Client, FastMCP

from hand_runtime.node_boundary import EffectBoundary
from hand_runtime.process_lease import ProcessLease
from modules.terminal.tools import register_terminal_tools
from node_protocol import Deployment
from node_protocol.effect import EffectVerifier

from .application.worker_lifespan import managed_lifespan
from .network_guard import read_attestation
from .presentation.catalogue import install_node_tools
from .worker_server import TerminalSupervisor, require_supervisor_isolation


def create_app(spec: Deployment) -> EffectBoundary:
    if spec.release.module != "terminal" or spec.release.run_as != "1000:1000":
        raise ValueError("Approved isolated Terminal contract required")
    network_facts = read_attestation(spec)
    require_supervisor_isolation(network_facts)
    verifier = EffectVerifier(spec)
    supervisor = TerminalSupervisor(
        spec.project_uuid,
        None,
        Path("/var/lib/terminal-supervisor"),
        execution_uid=1000,
        workspace_root="/project-data",
        prewarm=True,
        process_lease=ProcessLease(1000),
        network_facts=network_facts,
    )
    template, mcp = FastMCP("terminal-metadata"), FastMCP("briareus-node-terminal")
    # Preserve the original tools, signatures, descriptions and annotations.
    # These metadata closures are never executed in the privileged supervisor.
    register_terminal_tools(template, None)
    app = mcp.http_app(
        path="/mcp",
        stateless_http=True,
        json_response=True,
        host_origin_protection=True,
        allowed_hosts=[f"{spec.container_name}.terminal", "localhost"],
    )
    app.state.terminal_supervisor = supervisor

    def check_network() -> None:
        if read_attestation(spec) != network_facts:
            raise ValueError("Terminal network placement changed")

    async def prepare() -> None:
        await install_node_tools(
            mcp, template, supervisor, check_network if network_facts is not None else None
        )

    async def probe() -> None:
        async with Client(mcp, timeout=120) as client:
            await client.list_tools()

    app.router.lifespan_context = managed_lifespan(
        app.router.lifespan_context,
        supervisor,
        prepare,
        probe,
    )
    return EffectBoundary(
        app,
        verifier,
        code="TERMINAL_CURRENT_AUTHORITY_REQUIRED",
        ready=lambda: (
            supervisor.child_ready
            and supervisor.child is not None
            and supervisor.child.returncode is None
        ),
    )


def main() -> None:
    import uvicorn

    spec = Deployment.model_validate_json(os.environ["BRIAREUS_DEPLOYMENT"])
    os.umask(0o077)
    path = "/terminal-link/mcp.sock"
    parent = os.lstat("/terminal-link")
    if not stat.S_ISDIR(parent.st_mode) or (parent.st_uid, stat.S_IMODE(parent.st_mode)) != (
        0,
        0o700,
    ):
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
        uvicorn.Server(
            uvicorn.Config(
                create_app(spec), access_log=False, proxy_headers=False, timeout_graceful_shutdown=3
            )
        ).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
