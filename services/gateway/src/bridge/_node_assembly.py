"""Explicit private Core ports for node routing; no implicit trust fallback."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import TypeAdapter
from starlette.applications import Starlette

from node_protocol.effect import HumanPermitVerifier
from node_protocol.routing import NodeRoute
from runtime_peer import PeerClient, PeerIdentity

from ._core_admission import CoreAdmission
from ._node_routing import GatewayNodeRouter, ResourcesRoutes
from .thin_gateway import build_app


def configured_app() -> Starlette:
    mode = os.environ.get("MCP_NODE_ROUTING", "0")
    if mode == "0":
        return build_app()
    if mode != "1":
        raise ValueError("Explicit MCP node-routing mode required")
    signing = os.environ["GATEWAY_SIGNING_KEY_FILE"]
    origins = TypeAdapter(list[str]).validate_json(os.environ["BRIAREUS_NODE_ORIGINS"], strict=True)
    if len(origins) > 100 or len(set(origins)) != len(origins):
        raise ValueError("Bounded approved node origins required")
    for origin in origins:
        NodeRoute.canonical_origin(origin)
    access = PeerClient(
        name="briareus:gateway",
        signing_key_file=signing,
        socket_path=os.environ["MCP_ACCESS_SOCKET"],
        owner=PeerIdentity.from_file(
            "briareus:access",
            int(os.environ["MCP_ACCESS_UID"]),
            os.environ["MCP_ACCESS_VERIFY_KEY_FILE"],
        ),
    )
    resources = PeerClient(
        name="briareus:gateway",
        signing_key_file=signing,
        socket_path=os.environ["MCP_RESOURCES_SOCKET"],
        owner=PeerIdentity.from_file(
            "briareus:resources",
            int(os.environ["MCP_RESOURCES_UID"]),
            os.environ["MCP_RESOURCES_VERIFY_KEY_FILE"],
        ),
    )
    admission = CoreAdmission(access)
    app = build_app(
        private_decision=admission,
        node_router=GatewayNodeRouter(
            routes=ResourcesRoutes(resources),
            signing_key=access.key,
            allowed_origins=origins,
            effect_authority=admission,
            human_verifier=HumanPermitVerifier(
                Path(os.environ["MCP_ACCESS_VERIFY_KEY_FILE"]).read_bytes()
            ),
        ),
    )
    transport_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(current: Starlette) -> AsyncIterator[None]:
        try:
            async with transport_lifespan(current):
                yield
        finally:
            await access.close()
            await resources.close()

    app.router.lifespan_context = lifespan
    return app
