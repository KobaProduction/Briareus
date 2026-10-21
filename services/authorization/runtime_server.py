"""Private Core assembly for real human-issued AgentSession commands.

The BFF delegates a cookie-verified subject over a signed service channel.
Platform independently rechecks Rauthy status and current project ownership.
Only existing Access use cases create sessions, approvals and audit records.
This listener does not issue provider tokens or bypass resource-owner checks.
"""

from __future__ import annotations

import os
import stat
import logging
import hashlib
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

import jwt

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from runtime_peer import PeerClient, PeerIdentity, PeerVerifier, canonical_json
from runtime_peer.transport import _private_key
from runtime_peer.server import SignedOwnerApp, serve_unix

from authorization._approval_read_api import (
    ApprovalListCommand, ApprovalListReader, SessionGetCommand, VerifiedApprovalActor,
)
from authorization._idempotency import IdempotencyConflict, IdempotentCommandExecutor
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from authorization._access_cedar import permits_current_project_grant
from authorization._resource_scope import EffectResource
from authorization._rauthy_access_commands import (
    AccessRauthyCommandService, OpenSessionCommand, RequestElevationCommand,
    ResolveElevationCommand, RevokeSessionCommand, VerifiedAccessCommandActor,
)
from common.owner_migrations import verify_owner
from common.owner_runtime import VerifiedOwnerIngress, create_owner_app
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from common.platform_errors import AccessDenied, Conflict, InvalidInput

logger = logging.getLogger(__name__)


class ActorContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime
    permissions: tuple[Literal["use_resources", "approve_agent_session"], ...]
    role: Literal["user", "operator"]


class RuntimeAccessCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    actor_uuid: UUID
    project_uuid: UUID
    identity_expires_at: datetime
    action: Literal["session.open", "session.revoke", "session.list", "session.get",
                    "approval.list", "events.read", "session.request_elevation", "session.resolve_elevation",
                    "terminal.prepare", "files.prepare", "web.prepare", "resource.list"]
    command: dict[str, object] = Field(max_length=12)


@dataclass(frozen=True, slots=True)
class VerifiedHumanRequest:
    actor: ActorContext
    action: str


class HumanAttestor:
    @staticmethod
    def actor(request: Request, project_uuid: UUID) -> ActorContext:
        context = request.scope.get("briareus.verified_human_request")
        if (not isinstance(context, VerifiedHumanRequest)
            or request.scope.get("briareus.service_peer") != "briareus:control-panel-api"
            or context.actor.project_uuid != project_uuid
            or context.actor.expires_at <= datetime.now(UTC)):
            raise AccessDenied("Current independent Platform proof required")
        return context.actor

    async def verify(self, request: Request, command: object, action: str | None = None):
        actor = self.actor(request, command.project_uuid)
        approve = "approve_agent_session" in actor.permissions
        if action is None:
            return VerifiedApprovalActor(actor.actor_uuid, actor.project_uuid, approve,
                                          "rauthy", "briareus:access", actor.expires_at)
        if request.scope["briareus.verified_human_request"].action != action:
            raise AccessDenied("Human operation binding mismatch")
        return VerifiedAccessCommandActor(actor.actor_uuid, actor.project_uuid,
                                           command.operation_uuid, action,
                                           "use_resources" in actor.permissions, approve,
                                           "rauthy", "briareus:access", actor.expires_at)


class UnixIngress:
    def __init__(self, path: str) -> None:
        self.path = path

    async def verify_running_ingress(self) -> VerifiedOwnerIngress:
        info = os.stat(self.path)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o007:
            raise ValueError("Private Access listener unavailable")
        return VerifiedOwnerIngress("access", "unix-peer", True,
                                     datetime.now(UTC) + timedelta(seconds=10))


def create_runtime_app(path: str, platform: PeerClient, encryption_key: str,
                       terminal_worker: PeerClient | None = None, effect_key=None,
                       files_owner: PeerClient | None = None, web_owner: PeerClient | None = None,
                       mcp_issuers=None, node_resources: PeerClient | None = None):
    app = create_owner_app("access", trusted_ingress=UnixIngress(path))
    owner_lifespan = app.router.lifespan_context
    database = None
    commands = None
    reader = None
    attestor = HumanAttestor()
    from authorization._mcp_admission_runtime import mcp_admission_router
    app.include_router(mcp_admission_router(platform=platform, resolve_database=lambda: database,
        actor_model=ActorContext, issuers=mcp_issuers or {}))
    from authorization._node_files_effect import node_workspace_effect_router
    from authorization._mcp_call_journal import mcp_call_journal_router
    app.include_router(mcp_call_journal_router(resolve_database=lambda: database, signing_key=effect_key))
    from node_protocol.module_effects import MODULES
    for module in sorted(MODULES):
        app.include_router(node_workspace_effect_router(module=module, platform=platform, resources=node_resources,
            resolve_database=lambda: database, actor_model=ActorContext, issuers=mcp_issuers or {}, signing_key=effect_key))

    @asynccontextmanager
    async def lifespan(current_app):
        nonlocal database, commands, reader
        async with owner_lifespan(current_app):
            database = PlatformDatabase(OwnerDatabaseSettings(owner="access"))
            try:
                await verify_owner(database, OwnerDatabaseSettings(owner="access"))
                commands = AccessRauthyCommandService(
                    database=database, idempotency=IdempotentCommandExecutor(database, encryption_key),
                    attestor=attestor,
                )
                reader = ApprovalListReader(database=database, attestor=attestor)
                yield
            finally:
                commands = reader = None
                await database.close()
                database = None
                await platform.close()
                if terminal_worker is not None:
                    await terminal_worker.close()
                if files_owner is not None:
                    await files_owner.close()
                if web_owner is not None:
                    await web_owner.close()
                if node_resources is not None:
                    await node_resources.close()

    app.router.lifespan_context = lifespan

    @app.post("/internal/v1/runtime/access", include_in_schema=False)
    async def access(command: RuntimeAccessCommand, request: Request) -> JSONResponse:
        if commands is None or reader is None:
            raise HTTPException(503, "Access owner not ready")
        if request.scope.get("briareus.service_peer") != "briareus:control-panel-api":
            raise HTTPException(403, "Human management peer required")
        now = datetime.now(UTC)
        if (command.actor_uuid.version != 4 or command.project_uuid.version != 4
            or command.identity_expires_at.tzinfo is None
            or command.identity_expires_at <= now):
            raise HTTPException(401, "Current human identity required")
        try:
            status, raw_actor = await platform.call("/internal/v1/platform/oidc/actor-context", {
                "issuer": command.issuer, "subject": command.subject,
                "project_uuid": str(command.project_uuid),
            })
            if status != 200:
                raise AccessDenied("Current Platform actor unavailable")
            actor = ActorContext.model_validate(raw_actor)
            if (actor.issuer != command.issuer or actor.subject != command.subject
                or actor.actor_uuid != command.actor_uuid or actor.project_uuid != command.project_uuid
                or actor.expires_at.tzinfo is None
                or not now < actor.expires_at <= datetime.now(UTC) + timedelta(seconds=30)):
                raise AccessDenied("Platform context binding mismatch")
            actor = actor.model_copy(update={"expires_at": min(actor.expires_at, command.identity_expires_at)})
            request.scope["briareus.verified_human_request"] = VerifiedHumanRequest(actor, command.action)
            payload = {**command.command, "project_uuid": str(command.project_uuid)}
            if command.action == "events.read":
                from authorization._runtime_events import read_events
                return JSONResponse(await read_events(database, actor, command.command))
            if command.action in {"terminal.prepare", "files.prepare", "web.prepare", "resource.list"}:
                if "use_resources" not in actor.permissions:
                    raise AccessDenied("Current project resource permission required")
                hand = (command.command.get("hand", "terminal") if command.action == "resource.list"
                        else command.action.split(".")[0])
                if command.action == "resource.list":
                    from authorization._runtime_resource_owners import CurrentRuntimeResourceOwners
                    from node_protocol.module_effects import MODULES, RESOURCE_KINDS, effect_action
                    if hand not in MODULES or node_resources is None:
                        raise InvalidInput("Current Node resource owner unavailable")
                    binding = await CurrentRuntimeResourceOwners.node_workspace(node_resources, command.project_uuid, hand)
                    tools = None
                    if hand == "files":
                        from node_protocol import files
                        tools = files.READ_TOOLS | getattr(files, "WRITE_TOOLS", frozenset())
                    elif hand == "terminal":
                        from node_protocol.terminal import TOOLS
                        tools = TOOLS
                    return JSONResponse({
                        "items": [{"hand": hand, "tool": tool, "action": effect_action(hand, tool),
                            "resource": {"kind": RESOURCE_KINDS[hand], "id": binding.resource_id}}
                            for tool in sorted(tools or ())],
                        "resource": {"hand": hand, "kind": RESOURCE_KINDS[hand], "id": binding.resource_id},
                        "catalogue_state": "static" if tools is not None else "not_described",
                        "expires_at": min(actor.expires_at, datetime.fromtimestamp(binding.expires_at, UTC)).isoformat()})
                placements = {
                    "terminal": (terminal_worker, "terminal.execute", "workspace", "briareus:terminal-worker", 5),
                    "files": (files_owner, "files.read", "workspace_path", "briareus:files", 5),
                    "web": (web_owner, "web.access", "browser_session", "briareus:web", 20),
                }
                if hand not in placements:
                    raise InvalidInput("Runtime hand unavailable")
                owner, action, kind, audience, lease_seconds = placements[hand]
                if owner is None:
                    raise AccessDenied("Runtime resource owner not connected")
                status, placement = await owner.call("/internal/v1/" + hand + "/inspect", {})
                if (status != 200 or placement.get("project_uuid") != str(command.project_uuid)
                    or placement.get("isolated") is not True
                    or type(placement.get("resource_revision")) is not int
                    or placement.get("resource_id") != "project-" + hand + ":" + str(command.project_uuid) + ":" + format(placement["resource_revision"], "064x")
                    or placement["resource_revision"] < 1
                    or not isinstance(placement.get("tools"), list)
                    or not 1 <= len(placement["tools"]) <= 32
                    or any(not isinstance(tool, str) for tool in placement["tools"])):
                    raise AccessDenied("Current Terminal placement not verified")
                tools = placement["tools"]
                if command.action == "resource.list":
                    return JSONResponse({"items": [{
                        "hand": hand, "tool": tool, "action": action,
                        "resource": {"kind": kind, "id": placement["resource_id"]},
                    } for tool in tools], "expires_at": actor.expires_at.isoformat()})
                body = command.command
                if set(body) != {"tool", "arguments", "agent_session_uuid", "expected_grant_revision", "operation_uuid"}:
                    raise InvalidInput("Exact terminal command required")
                tool, arguments = body["tool"], body["arguments"]
                session_id, operation_id = UUID(body["agent_session_uuid"]), UUID(body["operation_uuid"])
                revision = body["expected_grant_revision"]
                if (tool not in tools or not isinstance(arguments, dict) or len(arguments) > 16
                    or type(revision) is not int or revision < 1
                    or session_id.version != 4 or operation_id.version != 4 or effect_key is None):
                    raise InvalidInput("Invalid terminal effect")
                resource = EffectResource(kind=kind, id=placement["resource_id"])
                async with database.transaction() as tx:
                    row = await tx.scalar(select(ProjectAgentSessionRow).where(
                        ProjectAgentSessionRow.session_uuid == session_id,
                        ProjectAgentSessionRow.project_id == command.project_uuid,
                    ).with_for_update())
                    if row is None or not permits_current_project_grant(
                        row=row, actor_uuid=actor.actor_uuid, project_uuid=actor.project_uuid,
                        operation=action, expected_version=revision,
                        hand=hand, tool=tool, resource=resource,
                    ):
                        raise AccessDenied("Current Cedar Terminal grant required")
                    if actor.expires_at <= datetime.now(UTC):
                        raise AccessDenied("Current Platform actor expired")
                    now_seconds = int(time.time())
                    expiry = min(now_seconds + lease_seconds, int(actor.expires_at.timestamp()),
                                 int(row.hard_expires_at.timestamp()))
                    if expiry <= now_seconds:
                        raise AccessDenied("Current authority expired")
                    from uuid import uuid4

                    permit = jwt.encode({
                        "iss": "briareus:authorization", "aud": audience,
                        "iat": now_seconds, "nbf": now_seconds, "exp": expiry,
                        "jti": str(uuid4()), "project_uuid": str(actor.project_uuid),
                        "actor_uuid": str(actor.actor_uuid), "session_uuid": str(session_id),
                        "grant_revision": revision, "tool": tool,
                        "arguments_digest": hashlib.sha256(canonical_json(arguments)).hexdigest(),
                        "resource_id": placement["resource_id"],
                        "resource_revision": placement["resource_revision"],
                        "operation_uuid": str(operation_id),
                    }, effect_key, algorithm="EdDSA", headers={"typ": "briareus-effect-permit+jwt"})
                    return JSONResponse({"permit": permit})
            if command.action == "session.list":
                result = await reader.list_sessions(request, ApprovalListCommand.model_validate(payload))
                return JSONResponse({"items": result})
            if command.action == "session.get":
                result = await reader.list_sessions(request, SessionGetCommand.model_validate(payload))
                if not result:
                    return JSONResponse({"error": {"code": "NOT_FOUND"}}, status_code=404)
                return JSONResponse({"item": result[0]})
            if command.action == "approval.list":
                result = await reader.list(request, ApprovalListCommand.model_validate(payload))
                return JSONResponse({"items": result})
            models = {
                "session.open": (OpenSessionCommand, commands.open_normal),
                "session.revoke": (RevokeSessionCommand, commands.revoke_session),
                "session.request_elevation": (RequestElevationCommand, commands.request_elevation),
                "session.resolve_elevation": (ResolveElevationCommand, commands.resolve_elevation),
            }
            model, execute = models[command.action]
            parsed = model.model_validate(payload)
            if command.action in {"session.request_elevation", "session.resolve_elevation"}:
                from authorization._runtime_resource_owners import CurrentRuntimeResourceOwners

                scopes = []
                if isinstance(parsed, RequestElevationCommand):
                    scopes = [item.model_dump(mode="json") for item in parsed.resources]
                elif parsed.approve:
                    async with database.transaction() as tx:
                        approval = await tx.scalar(select(SessionApprovalRow).where(
                            SessionApprovalRow.id == parsed.approval_uuid,
                            SessionApprovalRow.project_id == parsed.project_uuid,
                        ))
                        if approval is None or not isinstance(approval.requested_grants, dict):
                            raise AccessDenied("Current approval unavailable")
                        scopes = approval.requested_grants.get("resources", [])
                if scopes:
                    if not isinstance(scopes, list) or len(scopes) > 32:
                        raise AccessDenied("Current runtime resource owner unavailable")
                    owners = await CurrentRuntimeResourceOwners.inspect_owners(
                        {"terminal": terminal_worker, "files": files_owner, "web": web_owner}, command.project_uuid, scopes,
                        node_resources=node_resources)
                    scoped_commands = AccessRauthyCommandService(
                        database=database,
                        idempotency=IdempotentCommandExecutor(database, encryption_key),
                        attestor=attestor, resource_owner=owners,
                    )
                    execute = (scoped_commands.request_elevation if isinstance(parsed, RequestElevationCommand)
                               else scoped_commands.resolve_elevation)
            outcome = await execute(request, parsed)
            return JSONResponse(outcome.body, status_code=outcome.status)
        except AccessDenied as error:
            logger.warning("private Access command denied action=%s reason=%s", command.action, error)
            return JSONResponse({"error": {"code": "PROJECT_ACCESS_DENIED"}}, status_code=403)
        except (Conflict, IdempotencyConflict):
            return JSONResponse({"error": {"code": "REVISION_CONFLICT"}}, status_code=409)
        except (InvalidInput, ValidationError, ValueError):
            return JSONResponse({"error": {"code": "SCOPE_INVALID"}}, status_code=422)
        except OSError:
            return JSONResponse({"error": {"code": "RESOURCE_OWNER_UNAVAILABLE"}}, status_code=503)

    return app


def main() -> None:
    path = os.environ["ACCESS_RUNTIME_SOCKET"]
    signing_key = os.environ["ACCESS_RUNTIME_SIGNING_KEY_FILE"]
    platform = PeerClient(name="briareus:authorization", signing_key_file=signing_key,
                          socket_path=os.environ["PLATFORM_PANEL_SOCKET"],
                          owner=PeerIdentity.from_file("briareus:platform", 1000,
                                                       os.environ["PLATFORM_RUNTIME_VERIFY_KEY_FILE"]))
    terminal_worker = None
    if os.environ.get("TERMINAL_WORKER_SOCKET"):
        terminal_worker = PeerClient(
            name="briareus:authorization", signing_key_file=signing_key,
            socket_path=os.environ["TERMINAL_WORKER_SOCKET"],
            owner=PeerIdentity.from_file("briareus:terminal-worker", 0,
                                         os.environ["TERMINAL_WORKER_VERIFY_KEY_FILE"]),
        )
    files_owner = None
    if os.environ.get("FILES_RUNTIME_SOCKET"):
        files_owner = PeerClient(name="briareus:authorization", signing_key_file=signing_key,
            socket_path=os.environ["FILES_RUNTIME_SOCKET"],
            owner=PeerIdentity.from_file("briareus:files", 1004, os.environ["FILES_RUNTIME_VERIFY_KEY_FILE"]))
    web_owner = None
    if os.environ.get("WEB_RUNTIME_SOCKET"):
        web_owner = PeerClient(name="briareus:authorization", signing_key_file=signing_key,
            socket_path=os.environ["WEB_RUNTIME_SOCKET"],
            owner=PeerIdentity.from_file("briareus:web", 1005, os.environ["WEB_RUNTIME_VERIFY_KEY_FILE"]))
    from authorization._mcp_admission_runtime import configured_issuers
    node_resources = None
    if os.environ.get("RESOURCES_RUNTIME_SOCKET"):
        node_resources = PeerClient(name="briareus:authorization", signing_key_file=signing_key,
            socket_path=os.environ["RESOURCES_RUNTIME_SOCKET"],
            owner=PeerIdentity.from_file("briareus:resources", 1006, os.environ["RESOURCES_RUNTIME_VERIFY_KEY_FILE"]))
    app = create_runtime_app(path, platform, Path(os.environ["ACCESS_COMMAND_KEY_FILE"]).read_text().strip(),
                              terminal_worker, _private_key(signing_key), files_owner, web_owner,
                              mcp_issuers=configured_issuers(), node_resources=node_resources)
    callers = [
        PeerIdentity.from_file("briareus:control-panel-api", 1001, os.environ["ACCESS_PANEL_VERIFY_KEY_FILE"]),
    ]
    if os.environ.get("ACCESS_GATEWAY_VERIFY_KEY_FILE"):
        callers.append(PeerIdentity.from_file("briareus:gateway", 1000,
                                             os.environ["ACCESS_GATEWAY_VERIFY_KEY_FILE"]))
    verifier = PeerVerifier("briareus:access", tuple(callers))
    serve_unix(SignedOwnerApp(app, verifier=verifier, signing_key_file=signing_key), path,
               diagnostics_port=8000)


if __name__ == "__main__":
    main()
