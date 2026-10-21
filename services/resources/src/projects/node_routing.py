"""Resources-only route projection. Does not mint user or effect permissions."""
import json
import os
import time
from typing import Literal
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, UUID4
from sqlalchemy import select

from node_protocol import Deployment
from node_protocol.routing import NodeRoute
from node_protocol.effect import NodeWorkspaceBinding
from node_protocol.catalog import ARTIFACTS
from node_protocol.module_effects import MODULES, resource_id
from projects._node_persistence import (
    NodeRow, NodeModuleRow, NodeOperationRow, ModuleReleaseRow, ModuleArtifactRow, ProjectModuleBindingRow, NodeStorageRow,
)


class RouteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID4
    module: Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"]


class BrowserScopeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    actor_uuid: UUID4
    project_uuid: UUID4
    identity_expires_at: datetime


def route_router(resolve_database, *, platform=None, cipher=None):
    router = APIRouter()


    @router.post("/internal/v1/resources/node-route", include_in_schema=False)
    async def route(command: RouteQuery, request: Request):
        authority_path=request.scope.get("path")
        workspace_authority=authority_path in {"/internal/v1/resources/node-"+module+"-authority" for module in MODULES}
        if workspace_authority and authority_path != "/internal/v1/resources/node-" + command.module + "-authority":
            raise HTTPException(403,"Exact module authority required")
        expected_peer="briareus:authorization" if workspace_authority else "briareus:gateway"
        if request.scope.get("briareus.service_peer") != expected_peer:
            raise HTTPException(403, "Authenticated owner peer required")
        return await projection(command, workspace_authority)

    async def projection(command, workspace_authority):
        database = resolve_database()
        if database is None:
            raise HTTPException(503, "Resources unavailable")
        try:
            origins = json.loads(os.environ.get("BRIAREUS_NODE_ORIGINS", "[]"))
            if not isinstance(origins, list) or len(origins) > 100:
                raise ValueError("Explicit approved origins required")
            async with database.transaction() as tx:
                placement = await tx.scalar(select(NodeModuleRow).join(ProjectModuleBindingRow,
                    ProjectModuleBindingRow.placement_uuid == NodeModuleRow.id).where(
                        ProjectModuleBindingRow.project_uuid == command.project_uuid,
                        ProjectModuleBindingRow.logical_key == command.module,
                        NodeModuleRow.project_uuid == command.project_uuid,
                        NodeModuleRow.artifact_key == command.module, NodeModuleRow.state == "ready"))
                if placement is None or placement.applied_release_uuid is None:
                    raise HTTPException(503, "No ready project placement")
                node = await tx.get(NodeRow, placement.node_uuid)
                release = await tx.get(ModuleReleaseRow, placement.applied_release_uuid)
                artifact = await tx.get(ModuleArtifactRow, placement.artifact_key)
                applied = await tx.scalar(select(NodeOperationRow).where(
                    NodeOperationRow.placement_uuid == placement.id,
                    NodeOperationRow.node_uuid == placement.node_uuid,
                    NodeOperationRow.phase == "succeeded").order_by(NodeOperationRow.sequence.desc()).limit(1))
                if (node is None or node.deleted_at is not None or not node.enabled or not node.public_key
                    or node.endpoint not in origins or release is None or release.state != "published"
                    or release.artifact_key != command.module or applied is None
                    or artifact is None or not artifact.enabled):
                    raise HTTPException(503, "Current node placement unavailable")
                spec = Deployment.model_validate(applied.desired)
                if (not spec.enabled or spec.node_uuid != node.id or spec.id != placement.id
                    or spec.project_uuid != command.project_uuid or spec.release.module != command.module
                    or spec.release.image != release.image_reference or spec.fingerprint != applied.fingerprint
                    or spec.limits.model_dump() != placement.limits
                    or (spec.workspace.id if spec.workspace else None)!=placement.storage_uuid):
                    raise HTTPException(503, "Applied placement proof mismatch")
                projection = NodeRoute(node_uuid=node.id, placement_uuid=placement.id,
                    project_uuid=command.project_uuid, module=command.module, origin=node.endpoint,
                    fingerprint=spec.fingerprint, port=spec.release.port, expires_at=int(time.time()) + 5)
                if workspace_authority:
                    if spec.workspace is None or not spec.effect_verify_key:
                        raise HTTPException(503,"Approved Files workspace required")
                    storage=await tx.get(NodeStorageRow,spec.workspace.id)
                    if (storage is None or storage.node_uuid!=node.id or storage.project_uuid!=command.project_uuid
                        or storage.purpose!=ARTIFACTS[command.module].storage_purpose or storage.retention!="persistent"):
                        raise HTTPException(503,"Current workspace owner binding required")
                    projection=NodeWorkspaceBinding(node_uuid=node.id,placement_uuid=placement.id,
                        project_uuid=command.project_uuid,workspace_uuid=storage.id,fingerprint=spec.fingerprint,
                        effect_verify_key=spec.effect_verify_key,expires_at=projection.expires_at,
                        resource_revision=applied.sequence,
                        resource_id=resource_id(command.module,node.id,command.project_uuid,storage.id))
            if projection.expires_at <= time.time():
                raise HTTPException(503, "Route projection expired")
            return JSONResponse({"binding" if workspace_authority else "route": projection.model_dump(mode="json")}, headers={"Cache-Control": "no-store"})
        except ValueError:
            raise HTTPException(503, "Verified route configuration unavailable") from None

    @router.post("/internal/v1/resources/files-scope", include_in_schema=False)
    @router.post("/internal/v1/resources/analysis-scope", include_in_schema=False)
    @router.post("/internal/v1/resources/terminal-scope", include_in_schema=False)
    @router.post("/internal/v1/resources/browser-scope", include_in_schema=False)
    async def browser_scope(command: BrowserScopeQuery, request: Request):
        if request.scope.get("briareus.service_peer") != "briareus:control-panel-api" or platform is None:
            raise HTTPException(403, "Human management peer required")
        module = {"terminal":"terminal", "browser":"web", "files":"files", "analysis":"reverse"}[request.scope["path"].rsplit("/",1)[-1].removesuffix("-scope")]
        now = datetime.now(UTC)
        if command.identity_expires_at.tzinfo is None or not now < command.identity_expires_at <= now + timedelta(seconds=30):
            raise HTTPException(403, "Current identity required")
        status, actor = await platform.call("/internal/v1/platform/oidc/actor-context", {
            "issuer": command.issuer, "subject": command.subject, "project_uuid": str(command.project_uuid)})
        try:
            expiry = datetime.fromisoformat(actor["expires_at"])
            valid = (status == 200 and actor["issuer"] == command.issuer and actor["subject"] == command.subject
                and actor["actor_uuid"] == str(command.actor_uuid) and actor["project_uuid"] == str(command.project_uuid)
                and "use_resources" in actor["permissions"] and expiry.tzinfo is not None and now < expiry <= now + timedelta(seconds=30))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise HTTPException(403, "Current project membership required")
        response = await projection(RouteQuery(project_uuid=command.project_uuid, module=module), True)
        binding = json.loads(response.body)["binding"]
        if min(expiry, command.identity_expires_at) <= datetime.now(UTC):
            raise HTTPException(403, "Project proof expired")
        tools = ["local_browser_" + name for name in ("status", "pages", "open", "snapshot", "back", "forward", "reload",
            "close_page", "set_viewport", "click", "fill", "press", "select_option", "preview", "reopen_closed_page", "settings")]
        tools += ["web_operation_start", "web_operation_poll", "web_operation_cancel"]
        if module == "terminal":
            tools = ["terminal_status", "workspace_create", "job_start", "job_read", "job_cancel"]
        if module == "files":
            from node_protocol.files import READ_TOOLS, WRITE_TOOLS
            tools = sorted(READ_TOOLS | WRITE_TOOLS)
        elif module == "reverse":
            tools = ["analysis_tools", "analysis_call", "analysis_start", "analysis_poll", "analysis_cancel"]
        from node_protocol.module_effects import RESOURCE_KINDS, effect_action
        return JSONResponse({"items": [{"hand": module, "tool": tool, "action": effect_action(module,tool),
            "resource": {"kind": RESOURCE_KINDS[module], "id": binding["resource_id"]}} for tool in tools]},
            headers={"Cache-Control": "no-store"})

    for module in sorted(MODULES):
        router.add_api_route("/internal/v1/resources/node-"+module+"-authority", route,
                             methods=["POST"], include_in_schema=False)
    if platform is not None and cipher is not None:
        from projects.node_invocation import invocation_router

        async def current_binding(project, module, request):
            owner_request = Request({"type": "http", "method": "POST",
                "path": "/internal/v1/resources/node-"+module+"-authority",
                "briareus.service_peer": request.scope.get("briareus.service_peer")})
            response = await route(RouteQuery(project_uuid=project, module=module), owner_request)
            return NodeWorkspaceBinding.model_validate(json.loads(response.body)["binding"])

        router.include_router(invocation_router(platform=platform, cipher=cipher,
            resolve_database=resolve_database, resolve_binding=current_binding))
    return router
