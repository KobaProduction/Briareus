"""Authenticated human Node management boundary and owner composition root."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from common.platform_db import PlatformDatabase
from projects._node_persistence import NodeRow
from projects.application.node_administration import AuthorizeNodeOperator, ConfigureNode, ReadNodes
from projects.domain.node_administration import (
    ChangeNode,
    NewNode,
    NodeActor,
    NodeCommandIdentity,
    NodeConflict,
    NodeForbidden,
    NodeInvalid,
    NodeMissing,
    NodeReceiptUnavailable,
    NodeSourceUnavailable,
    OperatorAuthority,
    OperatorSelector,
)
from projects.infrastructure.node_administration import (
    NodeItemPayload,
    NodeSummaryPayload,
    PlatformActorSource,
    SqlNodeAdministrationTransactions,
    budget_record,
    node_record,
)
from projects.module_placements import PlacementManager
from projects.presentation.node_commands import NodeCommand as NodeCommand
from projects.presentation.node_commands import NodeRegistration as NodeRegistration
from runtime_peer import PeerClient

utc_now = partial(datetime.now, UTC)


def summary(row: NodeRow) -> NodeSummaryPayload:
    return NodeSummaryPayload.from_record(node_record(row))


class NodeRouter(APIRouter):
    def __init__(self, placements: PlacementManager) -> None:
        super().__init__()
        self.node_placements = placements


def management_error(
    error: NodeConflict
    | NodeForbidden
    | NodeInvalid
    | NodeMissing
    | NodeReceiptUnavailable
    | NodeSourceUnavailable,
) -> HTTPException:
    if isinstance(error, NodeForbidden):
        return HTTPException(403, str(error))
    if isinstance(error, NodeMissing):
        return HTTPException(404, str(error))
    if isinstance(error, (NodeSourceUnavailable, NodeReceiptUnavailable)):
        return HTTPException(503, str(error))
    if isinstance(error, NodeInvalid):
        return HTTPException(422, str(error))
    return HTTPException(409, str(error))


def configuration_command(command: NodeCommand) -> NewNode | ChangeNode:
    if command.action == "register":
        value = command.registration
        if (
            value is None
            or command.node_uuid is not None
            or command.name
            or command.expected_sequence
        ):
            raise HTTPException(422, "Exact node registration required")
        return NewNode(
            value.id,
            value.name,
            value.scope,
            value.owner_uuid,
            value.host_uuid,
            value.runtime_uid,
            value.endpoint,
            budget_record(value.budget),
        )
    if (
        command.node_uuid is None
        or command.expected_sequence is None
        or command.registration is not None
    ):
        raise HTTPException(422, "Existing node sequence required")
    if command.action not in {"rename", "disable"}:
        raise HTTPException(422, "Exact node configuration action required")
    return ChangeNode(command.node_uuid, command.expected_sequence, command.name, command.action)


def command_identity(command: NodeCommand) -> NodeCommandIdentity:
    if command.action not in {"register", "rename", "disable"}:
        raise HTTPException(422, "Exact node configuration action required")
    excluded = {
        "identity_expires_at",
        "module",
        "policy_scope",
        "policy_values",
        "expected_policy_sequence",
    }
    if command.budget is None:
        excluded.add("budget")
    digest = hashlib.sha256(
        json.dumps(
            command.model_dump(mode="json", exclude=excluded), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return NodeCommandIdentity(
        command.operation_uuid,
        command.actor_uuid,
        command.project_uuid,
        command.action,
        digest,
        command.expected_sequence,
    )


def validate_policy_fields(command: NodeCommand) -> None:
    if (
        command.policy_values is not None
        or command.expected_policy_sequence is not None
        or command.policy_scope != "server"
    ):
        raise HTTPException(422, "Runtime policy fields require runtime policy command")
    if (command.action == "budget") != (command.budget is not None):
        raise HTTPException(422, "Only budget configuration carries a node budget")


def validate_module_command(command: NodeCommand) -> None:
    if (
        command.module is None
        or command.registration is not None
        or command.node_uuid is not None
        or command.name
        or command.public_key
        or command.expected_sequence is not None
    ):
        raise HTTPException(422, "Exact module management command required")


class NodeOperatorBoundary:
    def __init__(self, authorize_operator: AuthorizeNodeOperator) -> None:
        self._authorize_operator = authorize_operator

    async def authorize(self, command: NodeCommand) -> OperatorAuthority:
        selector = OperatorSelector(
            command.issuer,
            command.subject,
            command.actor_uuid,
            command.project_uuid,
            command.identity_expires_at,
        )
        try:
            return await self._authorize_operator.execute(selector)
        except (NodeForbidden, NodeSourceUnavailable) as error:
            raise management_error(error) from None


class NodeManagementBoundary:
    def __init__(
        self,
        resolve_database: Callable[[], PlatformDatabase | None],
        cipher: Fernet,
        operator: NodeOperatorBoundary,
        placements: PlacementManager,
    ) -> None:
        self._resolve_database, self._cipher = resolve_database, cipher
        self._operator, self._placements = operator, placements

    async def modules(
        self, command: NodeCommand, database: PlatformDatabase, actor: NodeActor, expiry: datetime
    ) -> JSONResponse:
        validate_module_command(command)
        value = command.module
        if value is None:
            raise HTTPException(422, "Exact module management command required")
        if value.action in {"catalog", "publish"}:
            from projects.module_catalog import catalog_command

            return await catalog_command(
                command, database=database, cipher=self._cipher, expiry=expiry
            )
        if value.action in {"workspaces", "ensure_workspace"}:
            from projects.node_workspaces import workspace_command

            return await workspace_command(
                command, database=database, cipher=self._cipher, actor=actor, expiry=expiry
            )
        return await self._placements.command(command, expiry)

    async def nodes(self, command: NodeCommand, request: Request) -> JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:control-panel-api":
            raise HTTPException(403, "Human management peer required")
        database = self._resolve_database()
        if database is None:
            raise HTTPException(503, "Resources unavailable")
        actor, expiry = await self._operator.authorize(command)
        if command.action in {"runtime_policy", "runtime_policy_get"}:
            from projects.runtime_policy import policy_command

            return await policy_command(
                command, database=database, cipher=self._cipher, expiry=expiry
            )
        validate_policy_fields(command)
        if command.action == "modules":
            return await self.modules(command, database, actor, expiry)
        if command.module is not None:
            raise HTTPException(422, "Module command cannot accompany node configuration")
        if command.action in {"setup", "pair", "enable", "budget"}:
            from projects.node_enrollment import enroll

            return await enroll(
                command, database=database, cipher=self._cipher, authorize=self._operator.authorize
            )
        if command.public_key:
            raise HTTPException(422, "Only enrollment accepts a node public key")
        return await self.configure(command, database, actor, expiry)

    async def configure(
        self, command: NodeCommand, database: PlatformDatabase, actor: NodeActor, expiry: datetime
    ) -> JSONResponse:
        transactions = SqlNodeAdministrationTransactions(database, self._cipher)
        try:
            if command.action == "list":
                inventory = await ReadNodes(transactions, utc_now).execute(expiry)
                return JSONResponse(
                    {
                        "items": [
                            NodeSummaryPayload.from_record(node).model_dump(mode="json")
                            for node in inventory.items
                        ],
                        "truncated": inventory.truncated,
                    }
                )
            result = await ConfigureNode(transactions, utc_now).execute(
                command_identity(command), configuration_command(command), actor, expiry
            )
            return JSONResponse(
                NodeItemPayload(item=NodeSummaryPayload.from_record(result)).model_dump(mode="json")
            )
        except (
            NodeConflict,
            NodeForbidden,
            NodeInvalid,
            NodeMissing,
            NodeReceiptUnavailable,
        ) as error:
            raise management_error(error) from None
        except ValueError:
            raise HTTPException(422, "Invalid node configuration") from None


def node_router(
    *, platform: PeerClient, resolve_database: Callable[[], PlatformDatabase | None], cipher: Fernet
) -> NodeRouter:
    operator = NodeOperatorBoundary(AuthorizeNodeOperator(PlatformActorSource(platform), utc_now))
    placements = PlacementManager(resolve_database, operator.authorize)
    boundary = NodeManagementBoundary(resolve_database, cipher, operator, placements)
    router = NodeRouter(placements)
    router.add_api_route(
        "/internal/v1/resources/nodes", boundary.nodes, methods=["POST"], include_in_schema=False
    )
    from projects.node_routing import route_router

    router.include_router(route_router(resolve_database, platform=platform, cipher=cipher))
    return router
