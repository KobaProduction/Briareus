"""Composition root for private human Access commands and resource effects."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI

from authorization._human_web_effect import human_web_effect_router
from authorization._mcp_admission_runtime import mcp_admission_router
from authorization._mcp_call_journal import mcp_call_journal_router
from authorization._node_files_effect import node_workspace_effect_router
from authorization.infrastructure.mcp_issuers import ConfiguredMcpIssuers, McpIssuerRegistry
from authorization.infrastructure.runtime_handlers import RuntimePeers
from authorization.infrastructure.runtime_state import RuntimeDispatcherFactory, RuntimeState
from authorization.infrastructure.runtime_state import UnixIngress as UnixIngress
from authorization.presentation.runtime_attestor import HumanAttestor as HumanAttestor
from authorization.presentation.runtime_attestor import VerifiedHumanRequest as VerifiedHumanRequest
from authorization.presentation.runtime_http import RuntimeController
from authorization.presentation.runtime_protocol import ActorContext as ActorContext
from authorization.presentation.runtime_protocol import RuntimeAccessCommand as RuntimeAccessCommand
from common.owner_runtime import create_owner_app
from node_protocol.module_effects import MODULES
from runtime_peer import PeerClient, PeerIdentity, PeerVerifier
from runtime_peer.server import SignedOwnerApp, serve_unix
from runtime_peer.transport import _private_key


def create_runtime_app(
    path: str,
    platform: PeerClient,
    encryption_key: str,
    terminal_worker: PeerClient | None = None,
    effect_key: Ed25519PrivateKey | None = None,
    files_owner: PeerClient | None = None,
    web_owner: PeerClient | None = None,
    mcp_issuers: McpIssuerRegistry | None = None,
    node_resources: PeerClient | None = None,
) -> FastAPI:
    app = create_owner_app("access", trusted_ingress=UnixIngress(path))
    owner_lifespan = app.router.lifespan_context
    state = RuntimeState(
        RuntimePeers(platform, terminal_worker, files_owner, web_owner, node_resources),
        encryption_key,
    )
    issuers = mcp_issuers if mcp_issuers is not None else ConfiguredMcpIssuers(())
    app.include_router(
        mcp_admission_router(
            platform=platform,
            resolve_database=state.database,
            actor_model=ActorContext,
            issuers=issuers,
        )
    )
    app.include_router(
        mcp_call_journal_router(resolve_database=state.database, signing_key=effect_key)
    )
    app.include_router(
        human_web_effect_router(
            platform=platform,
            resources=node_resources,
            actor_model=ActorContext,
            issuers=issuers,
            signing_key=effect_key,
        )
    )
    for module in sorted(MODULES):
        app.include_router(
            node_workspace_effect_router(
                module=module,
                platform=platform,
                resources=node_resources,
                resolve_database=state.database,
                actor_model=ActorContext,
                issuers=issuers,
                signing_key=effect_key,
            )
        )

    @asynccontextmanager
    async def lifespan(current_app: FastAPI) -> AsyncIterator[None]:
        async with state.lifespan(current_app, owner_lifespan):
            yield

    app.router.lifespan_context = lifespan
    controller = RuntimeController(RuntimeDispatcherFactory(state, effect_key))
    app.add_api_route(
        "/internal/v1/runtime/access",
        controller.access,
        methods=["POST"],
        include_in_schema=False,
    )
    return app


def main() -> None:
    path = os.environ["ACCESS_RUNTIME_SOCKET"]
    signing_key = os.environ["ACCESS_RUNTIME_SIGNING_KEY_FILE"]
    platform = PeerClient(
        name="briareus:authorization",
        signing_key_file=signing_key,
        socket_path=os.environ["PLATFORM_PANEL_SOCKET"],
        owner=PeerIdentity.from_file(
            "briareus:platform", 1000, os.environ["PLATFORM_RUNTIME_VERIFY_KEY_FILE"]
        ),
    )
    terminal_worker = None
    if os.environ.get("TERMINAL_WORKER_SOCKET"):
        terminal_worker = PeerClient(
            name="briareus:authorization",
            signing_key_file=signing_key,
            socket_path=os.environ["TERMINAL_WORKER_SOCKET"],
            owner=PeerIdentity.from_file(
                "briareus:terminal-worker", 0, os.environ["TERMINAL_WORKER_VERIFY_KEY_FILE"]
            ),
        )
    files_owner = None
    if os.environ.get("FILES_RUNTIME_SOCKET"):
        files_owner = PeerClient(
            name="briareus:authorization",
            signing_key_file=signing_key,
            socket_path=os.environ["FILES_RUNTIME_SOCKET"],
            owner=PeerIdentity.from_file(
                "briareus:files", 1004, os.environ["FILES_RUNTIME_VERIFY_KEY_FILE"]
            ),
        )
    web_owner = None
    if os.environ.get("WEB_RUNTIME_SOCKET"):
        web_owner = PeerClient(
            name="briareus:authorization",
            signing_key_file=signing_key,
            socket_path=os.environ["WEB_RUNTIME_SOCKET"],
            owner=PeerIdentity.from_file(
                "briareus:web", 1005, os.environ["WEB_RUNTIME_VERIFY_KEY_FILE"]
            ),
        )
    from authorization._mcp_admission_runtime import configured_issuers

    node_resources = None
    if os.environ.get("RESOURCES_RUNTIME_SOCKET"):
        node_resources = PeerClient(
            name="briareus:authorization",
            signing_key_file=signing_key,
            socket_path=os.environ["RESOURCES_RUNTIME_SOCKET"],
            owner=PeerIdentity.from_file(
                "briareus:resources", 1006, os.environ["RESOURCES_RUNTIME_VERIFY_KEY_FILE"]
            ),
        )
    app = create_runtime_app(
        path,
        platform,
        Path(os.environ["ACCESS_COMMAND_KEY_FILE"]).read_text().strip(),
        terminal_worker,
        _private_key(signing_key),
        files_owner,
        web_owner,
        mcp_issuers=configured_issuers(),
        node_resources=node_resources,
    )
    callers = [
        PeerIdentity.from_file(
            "briareus:control-panel-api", 1001, os.environ["ACCESS_PANEL_VERIFY_KEY_FILE"]
        ),
    ]
    if os.environ.get("ACCESS_GATEWAY_VERIFY_KEY_FILE"):
        callers.append(
            PeerIdentity.from_file(
                "briareus:gateway", 1000, os.environ["ACCESS_GATEWAY_VERIFY_KEY_FILE"]
            )
        )
    verifier = PeerVerifier("briareus:access", tuple(callers))
    serve_unix(
        SignedOwnerApp(app, verifier=verifier, signing_key_file=signing_key),
        path,
        diagnostics_port=8000,
    )


if __name__ == "__main__":
    main()
