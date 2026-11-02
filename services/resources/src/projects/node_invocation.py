"""Stable entry points for Resources-owned private provider invocation."""

from collections.abc import Callable
from datetime import UTC, datetime

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request

from common.platform_db import PlatformDatabase
from projects.application.node_invocation import InvocationContext, PrepareNodeInvocation
from projects.domain.node_invocation import select_provider as selection
from projects.infrastructure.node_administration import PlatformActorSource
from projects.infrastructure.node_invocation import SqlInvocationAccounts
from projects.infrastructure.node_invocation import public_account as public_account
from projects.presentation.node_invocation import (
    InvocationBindingLookup,
    NodeInvocationBoundary,
    RequestInvocationPlacement,
)
from projects.presentation.node_invocation import (
    InvocationCommand as InvocationCommand,
)
from runtime_peer import PeerClient


async def project_accounts(
    database: PlatformDatabase,
    cipher: Fernet,
    command: InvocationCommand,
) -> InvocationContext:
    return await SqlInvocationAccounts(database, cipher).load(
        command.project_uuid,
        command.module,
        selection(command.module, command.arguments),
    )


def invocation_router(
    *,
    platform: PeerClient,
    cipher: Fernet,
    resolve_database: Callable[[], PlatformDatabase | None],
    resolve_binding: InvocationBindingLookup,
) -> APIRouter:
    router = APIRouter()

    def prepare(request: Request) -> PrepareNodeInvocation:
        database = resolve_database()
        if database is None:
            raise HTTPException(503, "Resources owner unavailable")
        return PrepareNodeInvocation(
            PlatformActorSource(platform),
            RequestInvocationPlacement(resolve_binding, request),
            SqlInvocationAccounts(database, cipher),
            lambda: datetime.now(UTC),
        )

    boundary = NodeInvocationBoundary(prepare)
    router.add_api_route(
        "/internal/v1/resources/node-invocation",
        boundary.invoke,
        methods=["POST"],
        include_in_schema=False,
    )
    return router
