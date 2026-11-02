"""Node composition and thin HTTP boundary; signed gRPC delivers Core commands."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import TypeAdapter
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from node_protocol import NodeRecord
from node_protocol.forward import ForwardVerifier
from node_protocol.runtime import rootless_budget

from .application.browser_observation import ObserveBrowser
from .application.control import NodeControl
from .application.control_results import operation_payload as receipt
from .control_auth import CoreVerifier
from .controller import Controller
from .dataplane import McpRelay, unavailable
from .docker_engine import DockerEngine
from .identity import NodeIdentity
from .infrastructure.browser_observation import NativeBrowserObservation
from .infrastructure.control import ControllerControlRuntime
from .infrastructure.controller_lock import ControllerLock
from .infrastructure.execution_tasks import NodeExecutionTasks
from .infrastructure.forward_admission import ForwardAdmission
from .infrastructure.journal_client import SignedJournalClient
from .infrastructure.journal_grpc import GrpcJournalRpc
from .infrastructure.lifespan import NodeLifespan
from .infrastructure.server_runtime import serve_controller
from .journal import Journal, JournalUnavailable, OperationConflict
from .presentation.control_endpoint import ControlEndpoint

__all__ = ["create_app", "main", "receipt"]


async def live(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "live"}, headers={"Cache-Control": "no-store"})


def create_app(
    node: NodeRecord,
    engine: DockerEngine,
    journal: Journal,
    verifier: CoreVerifier,
    identity: NodeIdentity | None = None,
    forward_verifier: ForwardVerifier | None = None,
    gateway_image: str | None = None,
    grpc_bind: str | None = None,
) -> Starlette:
    controller = Controller(node, engine, journal)
    tasks = NodeExecutionTasks(controller, journal)
    service = NodeControl(node, ControllerControlRuntime(controller), journal, tasks)
    relay = create_relay(
        forward_verifier, gateway_image, ForwardAdmission(controller, journal, service, tasks)
    )

    observer = (
        ObserveBrowser(NativeBrowserObservation(controller, service, tasks, relay.client))
        if relay is not None
        else None
    )

    control = ControlEndpoint(identity, journal, service, observer)

    async def mcp(request: Request) -> Response:
        return await relay.forward(request) if relay is not None else unavailable()

    async def ready(_request: Request) -> JSONResponse:
        try:
            await service.initialize()
        except (JournalUnavailable, OperationConflict, ValueError):
            return unavailable("NODE_RUNTIME_UNAVAILABLE")
        available = not tasks.draining()
        return JSONResponse(
            {"status": "ready" if available else "unavailable"},
            status_code=200 if available else 503,
            headers={"Cache-Control": "no-store"},
        )

    lifecycle = NodeLifespan(
        node=node,
        engine=engine,
        journal=journal,
        tasks=tasks,
        relay=relay,
        verifier=verifier,
        identity=identity,
        handler=control,
        gateway_image=gateway_image,
        grpc_bind=grpc_bind,
    )
    app = Starlette(
        routes=[
            Route("/health/live", live),
            Route("/health/ready", ready),
            Route(
                "/internal/v1/node/mcp",
                mcp,
                methods=["POST"],
            ),
        ],
        lifespan=lifecycle.run,
    )
    app.state.node_control = control
    return app


def create_relay(
    verifier: ForwardVerifier | None,
    gateway_image: str | None,
    admission: ForwardAdmission,
) -> McpRelay | None:
    if verifier is None:
        return None
    if not gateway_image:
        raise ValueError("An immutable Node Gateway image is required")
    return McpRelay(
        verifier=verifier,
        admit=admission,
        upstream_socket=True,
        client=httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds="/node-link/gateway.sock"),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(60, connect=3),
        ),
    )


def main() -> None:
    import uvicorn

    node = NodeRecord.model_validate_json(os.environ["BRIAREUS_NODE_RECORD"])
    rootless_budget(node.budget)
    if node.id != UUID(os.environ["BRIAREUS_NODE_UUID"]):
        raise ValueError("Configured enrollment does not match node UUID")
    verifier = CoreVerifier(os.environ["BRIAREUS_CORE_VERIFY_KEY"].encode(), node.id)
    engine = DockerEngine(
        f"/run/user/{os.getuid()}/docker.sock",
        allowed_registries=frozenset(
            TypeAdapter(list[str]).validate_json(
                os.environ["BRIAREUS_IMAGE_REGISTRIES"], strict=True
            )
        ),
    )
    identity = NodeIdentity(Path("/var/lib/briareus-node/node.key"))
    journal = Journal(
        SignedJournalClient(
            node.id,
            identity.key,
            verifier.key,
            GrpcJournalRpc(
                os.environ["BRIAREUS_NODE_JOURNAL_TARGET"],
                Path(os.environ["BRIAREUS_NODE_JOURNAL_CA_FILE"]),
            ),
        ),
        ControllerLock(Path("/var/lib/briareus-node/controller.lock")),
    )
    forwarding = ForwardVerifier(os.environ["BRIAREUS_GATEWAY_VERIFY_KEY"].encode(), node.id)
    config = uvicorn.Config(
        create_app(
            node,
            engine,
            journal,
            verifier,
            identity,
            forwarding,
            os.environ["BRIAREUS_NODE_IMAGE"],
            grpc_bind="0.0.0.0:8081",
        ),
        host="0.0.0.0",  # noqa: S104 -- isolated Node container; approved endpoint controls publication
        port=8080,
        access_log=False,
        proxy_headers=False,
        timeout_graceful_shutdown=10,
    )
    asyncio.run(serve_controller(uvicorn.Server(config), journal.lost))


if __name__ == "__main__":
    main()
