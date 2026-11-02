"""Project-scoped human connection management, owned by Resources.

Credentials are write-only, encrypted in the existing Catalog database. Current
Platform membership is independently checked on every command. This is not an
AgentSession grant or the external MCP execution plane.
"""

from __future__ import annotations

import os
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from common.owner_runtime import VerifiedOwnerIngress, create_owner_app
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from projects.application.provider_connections import (
    AuthorizeConnections,
    ManageConnections,
    VerifyProviderConnection,
)
from projects.infrastructure.node_administration import PlatformActorSource
from projects.infrastructure.provider_connections import (
    SqlConnectionEvents,
    SqlConnectionTransactions,
)
from projects.infrastructure.provider_verification import HTTPSProviderVerifier
from projects.node_journal_ingress import JournalServiceProvider
from projects.presentation.connection_commands import (
    ConnectionBoundary,
    connection_now,
)
from projects.presentation.connection_commands import (
    ConnectionCommand as ConnectionCommand,
)
from runtime_peer import PeerClient, PeerIdentity, PeerVerifier
from runtime_peer.server import SignedOwnerApp, serve_unix


def process_user_id() -> int:
    provider: object = getattr(os, "getuid", None)
    if not callable(provider):
        raise ValueError("Private Resources listener required")
    user_id: object = provider()
    if type(user_id) is not int:
        raise ValueError("Private Resources listener required")
    return user_id


class Ingress:
    async def verify_running_ingress(self) -> VerifiedOwnerIngress:
        info = os.stat(os.environ["RESOURCES_RUNTIME_SOCKET"])
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != process_user_id() or info.st_mode & 7:
            raise ValueError("Private Resources listener required")
        return VerifiedOwnerIngress(
            "resources", "unix-peer", True, datetime.now(UTC) + timedelta(seconds=10)
        )


def create_app(
    platform: PeerClient,
    cipher: Fernet,
    *,
    journal_provider: JournalServiceProvider | None = None,
) -> FastAPI:
    app = create_owner_app("resources", trusted_ingress=Ingress())
    owner_lifespan = app.router.lifespan_context
    database: PlatformDatabase | None = None
    if journal_provider is not None:
        journal_provider.bind_database(lambda: database)
    from projects.node_management import node_router

    nodes = node_router(platform=platform, resolve_database=lambda: database, cipher=cipher)
    app.include_router(nodes)

    @asynccontextmanager
    async def lifespan(current: FastAPI) -> AsyncIterator[None]:
        nonlocal database
        async with owner_lifespan(current):
            database = PlatformDatabase(OwnerDatabaseSettings(owner="resources"))
            try:
                if journal_provider is not None:
                    await journal_provider.start()
                yield
            finally:
                if journal_provider is not None:
                    await journal_provider.close()
                await nodes.node_placements.close()
                await database.close()
                database = None
                await platform.close()
                from projects.node_control import NodeControl

                if NodeControl.from_environment.cache_info().currsize:
                    await NodeControl.from_environment().close()

    app.router.lifespan_context = lifespan

    @app.post("/internal/v1/resources/connections", include_in_schema=False)
    async def connections(command: ConnectionCommand, request: Request) -> JSONResponse:
        if database is None:
            raise HTTPException(503, "Resources unavailable")
        boundary = ConnectionBoundary(
            AuthorizeConnections(PlatformActorSource(platform), connection_now),
            ManageConnections(SqlConnectionTransactions(database, cipher), connection_now),
            VerifyProviderConnection(HTTPSProviderVerifier()),
            SqlConnectionEvents(database),
            connection_now,
        )
        return await boundary.execute(command, request)

    return app


def main() -> None:
    signing_key = os.environ["RESOURCES_SIGNING_KEY_FILE"]
    platform = PeerClient(
        name="briareus:resources",
        signing_key_file=signing_key,
        socket_path=os.environ["PLATFORM_PANEL_SOCKET"],
        owner=PeerIdentity.from_file(
            "briareus:platform", 1000, os.environ["PLATFORM_RUNTIME_VERIFY_KEY_FILE"]
        ),
    )
    cipher = Fernet(Path(os.environ["RESOURCES_ENCRYPTION_KEY_FILE"]).read_bytes().strip())
    from projects.node_control import NodeControl

    control = NodeControl.from_environment()
    gateway_key: Ed25519PublicKey | None = None
    if control.gateway_verify_key is not None:
        candidate = serialization.load_pem_public_key(control.gateway_verify_key.encode())
        if not isinstance(candidate, Ed25519PublicKey):
            raise ValueError("Pinned Gateway Ed25519 identity required")
        gateway_key = candidate
    journal_provider = JournalServiceProvider(control.key, gateway_key)
    app = create_app(platform, cipher, journal_provider=journal_provider)
    callers = [
        PeerIdentity.from_file(
            "briareus:control-panel-api", 1001, os.environ["RESOURCES_PANEL_VERIFY_KEY_FILE"]
        ),
    ]
    if os.environ.get("RESOURCES_GATEWAY_VERIFY_KEY_FILE"):
        callers.append(
            PeerIdentity.from_file(
                "briareus:gateway", 1000, os.environ["RESOURCES_GATEWAY_VERIFY_KEY_FILE"]
            )
        )
    if os.environ.get("RESOURCES_ACCESS_VERIFY_KEY_FILE"):
        callers.append(
            PeerIdentity.from_file(
                "briareus:authorization", 1002, os.environ["RESOURCES_ACCESS_VERIFY_KEY_FILE"]
            )
        )
    signed = SignedOwnerApp(
        app,
        verifier=PeerVerifier("briareus:resources", tuple(callers)),
        signing_key_file=signing_key,
    )
    serve_unix(signed, os.environ["RESOURCES_RUNTIME_SOCKET"], diagnostics_port=8000)


if __name__ == "__main__":
    main()
