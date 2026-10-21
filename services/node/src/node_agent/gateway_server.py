"""Rootless Node Gateway. Only a private Unix listener; no engine credentials."""
import os
import socket
import stat
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse

from node_protocol.forward import ForwardVerifier
from .dataplane import McpRelay, worker_target
from .worker_transport import WorkerTransport


def create_app(verifier, *, client=None):
    relay = McpRelay(verifier=verifier, admit=worker_target, client=client or httpx.AsyncClient(
        transport=WorkerTransport(), trust_env=False, follow_redirects=False, timeout=httpx.Timeout(60, connect=3),
        limits=httpx.Limits(max_connections=32, max_keepalive_connections=8)))

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await relay.close()

    async def live(request):
        return JSONResponse({"status": "live"}, headers={"cache-control": "no-store"})
    app = Starlette(routes=[Route("/health/live", live),
        Route("/internal/v1/node/mcp", relay.forward, methods=["POST"])], lifespan=lifespan)
    app.state.relay = relay
    return app


def main():
    import uvicorn
    node = UUID(os.environ["BRIAREUS_NODE_UUID"])
    if node.version != 4:
        raise ValueError("Enrolled node UUID required")
    verifier = ForwardVerifier(os.environ["BRIAREUS_GATEWAY_VERIFY_KEY"].encode(), node)
    os.umask(0o077)
    path = "/node-link/gateway.sock"
    try:
        previous = os.lstat(path)
    except FileNotFoundError:
        previous = None
    if previous:
        if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid != os.getuid():
            raise ValueError("Refusing to replace a foreign Gateway socket")
        os.unlink(path)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(path)
        os.chmod(path, 0o600)
        listener.listen(128)
        uvicorn.Server(uvicorn.Config(create_app(verifier), access_log=False,
            proxy_headers=False, timeout_graceful_shutdown=10)).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
