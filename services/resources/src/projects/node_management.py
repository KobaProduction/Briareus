"""Human node inventory/registration through Resources' authenticated peer.

Operator management never grants MCP execution. Owner UUIDs are verified from
current Platform metadata; arbitrary browser ownership assertions are rejected.
"""
from __future__ import annotations
from node_protocol.models import RuntimePolicyOverrides

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow
from projects._node_persistence import NodeRow
from node_protocol.management import ModuleCommand
from node_protocol import NodeBudget


class NodeRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID4
    name: str = Field(min_length=1, max_length=128)
    scope: Literal["personal", "team", "shared"]
    owner_uuid: UUID4 | None = None
    host_uuid: UUID4
    runtime_uid: int = Field(strict=True, ge=2000, le=2**31 - 1)
    endpoint: str = Field(max_length=512)
    # Validate using the shared immutable wire contract at the owner boundary.
    budget: dict = Field(max_length=2)


    @field_validator("name")
    @classmethod
    def name_valid(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Printable node name required")
        return value

    @field_validator("endpoint")
    @classmethod
    def endpoint_valid(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", parsed.hostname)
            or parsed.port not in {None, 443}):
            raise ValueError("Canonical HTTPS node origin required")
        return "https://" + parsed.hostname


class NodeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    actor_uuid: UUID4
    project_uuid: UUID4
    identity_expires_at: datetime
    operation_uuid: UUID4
    action: Literal["list", "register", "rename", "disable", "setup", "pair", "enable", "budget", "modules", "runtime_policy", "runtime_policy_get"]
    registration: NodeRegistration | None = None
    node_uuid: UUID4 | None = None
    name: str = Field(default="", max_length=128)
    expected_sequence: int | None = Field(default=None, strict=True, ge=1)
    public_key: str = Field(default="", max_length=256)
    module: ModuleCommand | None = None
    budget: NodeBudget | None = None
    policy_scope: Literal["server", "node"] = "server"
    policy_values: RuntimePolicyOverrides | None = None
    expected_policy_sequence: int | None = Field(default=None, strict=True, ge=0)


def summary(row):
    return {"id": str(row.id), "name": row.name, "scope": row.scope,
            "owner_uuid": str(row.owner_uuid) if row.owner_uuid else None,
            "host_uuid": str(row.host_uuid), "runtime_uid": row.runtime_uid,
            "endpoint": row.endpoint, "budget": row.budget, "enabled": row.enabled,
            "paired": bool(row.public_key),
            "sequence": row.sequence, "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "created_at": row.created_at.isoformat()}


def node_router(*, platform, resolve_database, cipher):
    router = APIRouter()

    async def authorize(command):
        now = datetime.now(UTC)
        deadline = command.identity_expires_at
        if deadline.tzinfo is None or not now < deadline <= now + timedelta(seconds=30):
            raise HTTPException(403, "Current project identity required")
        status, actor = await platform.call("/internal/v1/platform/oidc/actor-context", {
            "issuer": command.issuer, "subject": command.subject,
            "project_uuid": str(command.project_uuid),
        })
        if status != 200:
            raise HTTPException(403 if status == 403 else 503, "Current Platform source required")
        try:
            expiry = datetime.fromisoformat(actor["expires_at"])
            valid = (actor["issuer"] == command.issuer and actor["subject"] == command.subject
                     and actor["actor_uuid"] == str(command.actor_uuid)
                     and actor["project_uuid"] == str(command.project_uuid)
                     and actor["role"] == "operator" and "use_resources" in actor["permissions"]
                     and expiry.tzinfo is not None and now < expiry <= now + timedelta(seconds=30))
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            raise HTTPException(403, "Current Platform operator required")
        return actor, min(deadline, expiry)

    from projects.module_placements import PlacementManager
    placements=PlacementManager(resolve_database,authorize)
    router.node_placements=placements

    @router.post("/internal/v1/resources/nodes", include_in_schema=False)
    async def nodes(command: NodeCommand, request: Request):
        if request.scope.get("briareus.service_peer") != "briareus:control-panel-api":
            raise HTTPException(403, "Human management peer required")
        database = resolve_database()
        if database is None:
            raise HTTPException(503, "Resources unavailable")
        actor, expiry = await authorize(command)
        if command.action in {"runtime_policy", "runtime_policy_get"}:
            from projects.runtime_policy import policy_command
            return await policy_command(command,database=database,cipher=cipher,expiry=expiry)
        if command.policy_values is not None or command.expected_policy_sequence is not None or command.policy_scope!="server":
            raise HTTPException(422,"Runtime policy fields require runtime policy command")
        if (command.action == "budget") != (command.budget is not None):
            raise HTTPException(422,"Only budget configuration carries a node budget")
        if command.action == "modules":
            if (command.module is None or command.registration is not None or command.node_uuid is not None
                or command.name or command.public_key or command.expected_sequence is not None):
                raise HTTPException(422,"Exact module management command required")
            from projects.module_catalog import catalog_command
            if command.module.action in {"catalog","publish"}:
                return await catalog_command(command,database=database,cipher=cipher,expiry=expiry)
            if command.module.action in {"workspaces","ensure_workspace"}:
                from projects.node_workspaces import workspace_command
                return await workspace_command(command,database=database,cipher=cipher,actor=actor,expiry=expiry)
            return await placements.command(command,expiry)
        if command.module is not None:
            raise HTTPException(422,"Module command cannot accompany node configuration")
        if command.action in {"setup", "pair", "enable", "budget"}:
            from projects.node_enrollment import enroll
            return await enroll(command, database=database, cipher=cipher, authorize=authorize)
        if command.public_key:
            raise HTTPException(422, "Only enrollment accepts a node public key")
        payload = command.model_dump(mode="json", exclude={"identity_expires_at", "module", "policy_scope", "policy_values", "expected_policy_sequence"} | ({"budget"} if command.budget is None else set()))
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        action = "node." + command.action
        try:
            async with database.transaction() as tx:
                if command.action == "list":
                    rows = list(await tx.scalars(select(NodeRow).where(NodeRow.deleted_at.is_(None))
                                                .order_by(NodeRow.name, NodeRow.id).limit(101)))
                    if expiry <= datetime.now(UTC):
                        raise HTTPException(403, "Platform proof expired")
                    return JSONResponse({"items": [summary(row) for row in rows[:100]], "truncated": len(rows) > 100})
                existing = await tx.scalar(select(OwnerCommandRow).where(
                    OwnerCommandRow.operation_uuid == command.operation_uuid,
                    OwnerCommandRow.operation == action).with_for_update())
                if existing is not None:
                    if (existing.fingerprint != digest or existing.actor_scope != str(command.actor_uuid)
                        or existing.project_scope != str(command.project_uuid) or existing.state != "completed"):
                        raise HTTPException(409, "Operation identity conflict")
                    outcome = json.loads(cipher.decrypt(existing.encrypted_outcome.encode()))
                    if outcome["digest"] != digest or outcome["operation"] != str(command.operation_uuid):
                        raise HTTPException(503, "Operation receipt unavailable")
                    if expiry <= datetime.now(UTC):
                        raise HTTPException(403, "Platform proof expired")
                    return JSONResponse(outcome["result"])
                if command.action == "register":
                    value = command.registration
                    if value is None or command.node_uuid is not None or command.name or command.expected_sequence:
                        raise HTTPException(422, "Exact node registration required")
                    from node_protocol import NodeBudget
                    budget = NodeBudget.model_validate(value.budget).model_dump(mode="json")
                    permitted_owner = (value.owner_uuid is None if value.scope == "shared" else
                        str(value.owner_uuid) == (str(command.actor_uuid) if value.scope == "personal" else
                            actor.get("project_owner_uuid") if actor.get("project_owner_kind") == "team" else None))
                    if not permitted_owner:
                        raise HTTPException(403, "Node owner must match current Platform scope")
                    if await tx.get(NodeRow, value.id) is not None:
                        raise HTTPException(409, "Node already registered")
                    row = NodeRow(**value.model_dump(exclude={"budget"}), budget=budget,
                                  enabled=False, sequence=1, created_at=datetime.now(UTC))
                    tx.add(row)
                else:
                    if (command.node_uuid is None or command.expected_sequence is None
                        or command.registration is not None):
                        raise HTTPException(422, "Existing node sequence required")
                    row = await tx.scalar(select(NodeRow).where(NodeRow.id == command.node_uuid,
                        NodeRow.deleted_at.is_(None)).with_for_update())
                    if row is None:
                        raise HTTPException(404, "Node not found")
                    if row.sequence != command.expected_sequence:
                        raise HTTPException(409, "Node configuration changed")
                    if command.action == "rename":
                        name = command.name.strip()
                        if not name or any(ord(char) < 32 for char in name):
                            raise HTTPException(422, "Printable node name required")
                        row.name = name
                    else:
                        if command.name:
                            raise HTTPException(422, "Disable does not rename a node")
                        row.enabled = False
                    row.sequence += 1
                await tx.flush()
                result = {"item": summary(row)}
                if expiry <= datetime.now(UTC):
                    raise HTTPException(403, "Platform proof expired")
                tx.add(OwnerCommandRow(operation_uuid=command.operation_uuid,
                    actor_scope=str(command.actor_uuid), project_scope=str(command.project_uuid),
                    operation=action, key=str(command.operation_uuid), fingerprint=digest,
                    expected_owner_revision=str(command.expected_sequence or 0), state="completed",
                    encrypted_outcome=cipher.encrypt(json.dumps({"operation": str(command.operation_uuid),
                        "digest": digest, "result": result}).encode()).decode(),
                    expires_at=datetime.now(UTC) + timedelta(days=7)))
                tx.add(OwnerAuditRow(operation_uuid=command.operation_uuid, actor_user_id=command.actor_uuid,
                    project_id=command.project_uuid, action=action, object_id=str(row.id),
                    owner_revision=str(row.sequence), details={"scope": row.scope}))
            return JSONResponse(result)
        except IntegrityError:
            raise HTTPException(409, "Node identity or operation conflicts; retry the same operation") from None
        except ValueError:
            raise HTTPException(422, "Invalid node configuration") from None

    from projects.node_routing import route_router
    router.include_router(route_router(resolve_database, platform=platform, cipher=cipher))
    return router
