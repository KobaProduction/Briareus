"""Node management over the existing authenticated Panel WebSocket."""
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, UUID4

from ._panel_rpc import RpcFailure


class NodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_uuid: UUID4
    operation_uuid: UUID4
    action: Literal["list", "register", "rename", "disable", "setup", "pair", "enable", "budget", "modules", "runtime_policy", "runtime_policy_get"]
    registration: dict | None = Field(default=None, max_length=9)
    node_uuid: UUID4 | None = None
    name: str = Field(default="", max_length=128)
    expected_sequence: int | None = Field(default=None, strict=True, ge=1)
    public_key: str = Field(default="", max_length=256)
    module: dict | None = Field(default=None,max_length=2)
    budget: dict | None = Field(default=None,max_length=2)
    policy_scope: Literal["server", "node"] = "server"
    policy_values: dict[str,object] | None = Field(default=None,max_length=4)
    expected_policy_sequence: int | None = Field(default=None, strict=True, ge=0)



async def node_call(*, socket, method, params, current_context, resources):
    try:
        if method == "nodes.inventory":
            if set(params) != {"project_uuid"}:
                raise ValueError
            data = NodeInput(project_uuid=params["project_uuid"], operation_uuid=uuid4(), action="list")
        else:
            data = NodeInput.model_validate(params)
            if data.action == "list":
                raise ValueError
    except ValueError:
        raise RpcFailure("NODE_COMMAND_INVALID") from None
    current = await current_context(socket, data.project_uuid)
    if isinstance(current, JSONResponse):
        raise RpcFailure("CURRENT_PLATFORM_REQUIRED")
    session, proof = current
    if proof.role != "operator":
        raise RpcFailure("PLATFORM_OPERATOR_REQUIRED")
    if resources is None:
        raise RpcFailure("NODE_OWNER_UNAVAILABLE")
    expires = min(session.expires_at, proof.expires_at)
    wire = data.model_dump(mode="json")
    if not data.action.startswith("runtime_policy"):
        for key in ("policy_scope","policy_values","expected_policy_sequence"):wire.pop(key,None)
    wire.update(issuer=proof.issuer, subject=proof.subject, actor_uuid=str(proof.user_uuid),
                identity_expires_at=expires.isoformat())
    mutation = data.action not in {"list", "setup", "runtime_policy_get"} and not (data.action=="modules" and data.module and data.module.get("action") in {"catalog","placements","workspaces"})
    try:
        status, result = await resources.call("/internal/v1/resources/nodes", wire)
    except Exception:
        raise RpcFailure("NODE_OUTCOME_UNKNOWN", uncertain=mutation) from None
    if status != 200:
        raise RpcFailure({403: "NODE_PERMISSION_DENIED", 404: "NODE_NOT_FOUND",
                          409: "NODE_CONFIGURATION_CONFLICT", 422: "NODE_COMMAND_INVALID"}.get(status,
                           "NODE_OWNER_UNAVAILABLE"), uncertain=mutation and status >= 500)
    fresh = await current_context(socket, data.project_uuid)
    if (isinstance(fresh, JSONResponse) or fresh[1].user_uuid != proof.user_uuid
        or fresh[1].role != "operator" or fresh[0].subject != session.subject
        or expires <= datetime.now(UTC)):
        raise RpcFailure("NODE_OUTCOME_UNKNOWN", uncertain=mutation)
    if mutation:
        from ._panel_events import panel_events
        await panel_events.emit("management.events", "node." + data.action,
            {"node_id": result.get("item", {}).get("id"), "actor_id": str(proof.user_uuid)},
            visibility={"kind": "operator"})
    return result
