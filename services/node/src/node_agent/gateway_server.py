"""Rootless Node Gateway. Only a private Unix listener; no engine credentials."""

import os
import socket
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from node_protocol.browser_observation import OBSERVATION_PATH
from node_protocol.control_auth import CoreVerifier
from node_protocol.forward import ForwardVerifier

from .dataplane import McpRelay, worker_target
from .infrastructure.browser_observation_relay import BrowserObservationRelay
from .worker_transport import WorkerTransport


def create_app(
    verifier: ForwardVerifier,
    *,
    client: httpx.AsyncClient | None = None,
    core_verifier: CoreVerifier | None = None,
) -> Starlette:
    relay = McpRelay(
        verifier=verifier,
        admit=worker_target,
        client=client
        or httpx.AsyncClient(
            transport=WorkerTransport(),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(60, connect=3),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=8),
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await relay.close()

    async def live(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "live"}, headers={"cache-control": "no-store"})

    observer = BrowserObservationRelay(core_verifier, relay.client)
    app = Starlette(
        routes=[
            Route("/health/live", live),
            Route("/internal/v1/node/mcp", relay.forward, methods=["POST"]),
            Route(OBSERVATION_PATH, observer.forward, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
    app.state.relay = relay
    return app


def main() -> None:
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
        uvicorn.Server(
            uvicorn.Config(
                create_app(
                    verifier,
                    core_verifier=CoreVerifier(
                        os.environ["BRIAREUS_CORE_VERIFY_KEY"].encode(), node
                    )
                    if os.environ.get("BRIAREUS_CORE_VERIFY_KEY")
                    else None,
                ),
                access_log=False,
                proxy_headers=False,
                timeout_graceful_shutdown=10,
            )
        ).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
