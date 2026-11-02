"""Adapt management commands to the independent project workspace use case."""

import hashlib
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from common.platform_db import PlatformDatabase
from node_protocol.control import canonical
from projects.application.project_workspaces import ProjectWorkspaces
from projects.domain.node_administration import NodeActor
from projects.domain.project_workspaces import WorkspaceActor, WorkspaceIdentity, WorkspaceRejected
from projects.infrastructure.project_workspaces import SqlWorkspaceTransactions, WorkspacePayload

if TYPE_CHECKING:
    from projects.presentation.node_commands import NodeCommand


now = partial(datetime.now, UTC)


async def workspace_command(
    command: "NodeCommand",
    *,
    database: PlatformDatabase,
    cipher: Fernet,
    actor: NodeActor,
    expiry: datetime,
) -> JSONResponse:
    if command.module is None or command.module.node_uuid is None:
        raise HTTPException(422, "Exact workspace command required")
    node_uuid = command.module.node_uuid
    digest = hashlib.sha256(
        canonical({"node_uuid": str(node_uuid), "project_uuid": str(command.project_uuid)})
    ).hexdigest()
    principal = WorkspaceActor(
        command.actor_uuid,
        actor.project_owner_kind,
        str(actor.project_owner_uuid) if actor.project_owner_uuid is not None else None,
    )
    identity = WorkspaceIdentity(
        command.operation_uuid, command.actor_uuid, command.project_uuid, node_uuid, digest
    )
    try:
        result = await ProjectWorkspaces(SqlWorkspaceTransactions(database, cipher), now).execute(
            identity, principal, ensure=command.module.action == "ensure_workspace", expiry=expiry
        )
    except WorkspaceRejected as exc:
        raise HTTPException(403 if exc.forbidden else 409, str(exc)) from None
    item = WorkspacePayload.from_record(result.workspace) if result.workspace is not None else None
    if result.ensured:
        return JSONResponse(
            {"item": item.model_dump(mode="json") if item else None},
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        {"items": [item.model_dump(mode="json")] if item else []},
        headers={"Cache-Control": "no-store"},
    )
