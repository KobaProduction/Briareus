"""Authenticate route consumers and adapt typed owner projections to existing HTTP schemas."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import UUID4, BaseModel, ConfigDict, Field

from common.platform_db import PlatformDatabase
from node_protocol.effect import NodeWorkspaceBinding, NodeWorkspaceReply
from node_protocol.files import READ_TOOLS, WRITE_TOOLS
from node_protocol.module_effects import MODULES, RESOURCE_KINDS, effect_action
from node_protocol.routing import NodeRoute, NodeRouteReply
from projects.application.node_routing import AuthorizeHumanScope, ProjectNodeProjection
from projects.domain.node_administration import OperatorSelector
from projects.domain.node_routing import RoutedModule
from projects.domain.provider_connections import ConnectionFailure
from projects.infrastructure.node_administration import PlatformActorSource
from projects.infrastructure.node_routing import SqlRouteEvidence
from runtime_peer import PeerClient
from runtime_peer.human_scope import HumanScopeReceipt, ScopeItem, ScopeResource

_AUTHORITY_PATHS = frozenset(
    "/internal/v1/resources/node-" + module + "-authority" for module in MODULES
)
_SCOPE_MODULES: dict[str, RoutedModule] = {
    "terminal": "terminal",
    "browser": "web",
    "files": "files",
    "analysis": "reverse",
}


class RouteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID4
    module: RoutedModule


class BrowserScopeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    actor_uuid: UUID4
    project_uuid: UUID4
    identity_expires_at: datetime


def _human_tools(module: RoutedModule) -> tuple[str, ...]:
    if module == "terminal":
        from node_protocol.terminal import TOOLS as TERMINAL_TOOLS

        return tuple(sorted(TERMINAL_TOOLS))
    if module == "files":
        return tuple(sorted(READ_TOOLS | WRITE_TOOLS))
    if module == "reverse":
        return (
            "analysis_tools",
            "analysis_call",
            "analysis_start",
            "analysis_poll",
            "analysis_cancel",
        )
    browser = tuple(
        "local_browser_" + name
        for name in (
            "status",
            "pages",
            "open",
            "snapshot",
            "back",
            "forward",
            "reload",
            "close_page",
            "set_viewport",
            "click",
            "fill",
            "press",
            "select_option",
            "preview",
            "reopen_closed_page",
            "settings",
            "input",
        )
    )
    return (*browser, "web_operation_start", "web_operation_poll", "web_operation_cancel")


def _require_owner_peer(path: object, peer: object, module: RoutedModule) -> bool:
    workspace = isinstance(path, str) and path in _AUTHORITY_PATHS
    if workspace and path != "/internal/v1/resources/node-" + module + "-authority":
        raise HTTPException(403, "Exact module authority required")
    expected = "briareus:authorization" if workspace else "briareus:gateway"
    if peer != expected:
        raise HTTPException(403, "Authenticated owner peer required")
    return workspace


class NodeRoutingBoundary:
    def __init__(
        self,
        resolve_database: Callable[[], PlatformDatabase | None],
        platform: PeerClient | None,
    ) -> None:
        self._resolve_database = resolve_database
        self._platform = PlatformActorSource(platform) if platform is not None else None

    async def _projection(
        self,
        project: UUID,
        module: RoutedModule,
        *,
        workspace: bool,
    ) -> NodeRoute | NodeWorkspaceBinding:
        database = self._resolve_database()
        if database is None:
            raise HTTPException(503, "Resources unavailable")
        try:
            return await ProjectNodeProjection(
                SqlRouteEvidence(database), lambda: datetime.now(UTC)
            ).execute(project, module, workspace=workspace)
        except ConnectionFailure as exc:
            raise HTTPException(exc.status, exc.detail) from None
        except ValueError:
            raise HTTPException(503, "Verified route configuration unavailable") from None

    async def route(self, command: RouteQuery, request: Request) -> JSONResponse:
        workspace = _require_owner_peer(
            request.scope.get("path"), request.scope.get("briareus.service_peer"), command.module
        )
        result = await self._projection(command.project_uuid, command.module, workspace=workspace)
        reply: NodeWorkspaceReply | NodeRouteReply
        if workspace and isinstance(result, NodeWorkspaceBinding):
            reply = NodeWorkspaceReply(binding=result)
        elif not workspace and isinstance(result, NodeRoute):
            reply = NodeRouteReply(route=result)
        else:
            raise HTTPException(503, "Verified route configuration unavailable")
        return JSONResponse(
            reply.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    async def _workspace(self, project: UUID, module: RoutedModule) -> NodeWorkspaceBinding:
        result = await self._projection(project, module, workspace=True)
        if not isinstance(result, NodeWorkspaceBinding):
            raise HTTPException(503, "Verified workspace binding unavailable")
        return result

    async def current_binding(
        self,
        project: UUID,
        module: str,
        request: Request,
    ) -> NodeWorkspaceBinding:
        command = RouteQuery.model_validate({"project_uuid": project, "module": module})
        _require_owner_peer(
            "/internal/v1/resources/node-" + command.module + "-authority",
            request.scope.get("briareus.service_peer"),
            command.module,
        )
        return await self._workspace(project, command.module)

    async def browser_scope(self, command: BrowserScopeQuery, request: Request) -> JSONResponse:
        peer = request.scope.get("briareus.service_peer")
        human_authority = peer == "briareus:authorization" and request.scope.get("path") in {
            "/internal/v1/resources/browser-scope",
            "/internal/v1/resources/files-scope",
            "/internal/v1/resources/terminal-scope",
            "/internal/v1/resources/analysis-scope",
        }
        if peer != "briareus:control-panel-api" and not human_authority:
            raise HTTPException(403, "Human management peer required")
        if self._platform is None:
            raise HTTPException(403, "Human management peer required")
        scope = request.scope["path"].rsplit("/", 1)[-1].removesuffix("-scope")
        module = _SCOPE_MODULES[scope]
        selector = OperatorSelector(
            command.issuer,
            command.subject,
            command.actor_uuid,
            command.project_uuid,
            command.identity_expires_at,
        )
        try:
            expiry = await AuthorizeHumanScope(self._platform, lambda: datetime.now(UTC)).execute(
                selector
            )
        except ConnectionFailure as exc:
            raise HTTPException(exc.status, exc.detail) from None
        binding = await self._workspace(command.project_uuid, module)
        if expiry <= datetime.now(UTC):
            raise HTTPException(403, "Project proof expired")
        return JSONResponse(
            HumanScopeReceipt(
                items=tuple(
                    ScopeItem(
                        hand=module,
                        tool=tool,
                        action=effect_action(module, tool),
                        resource=ScopeResource(kind=RESOURCE_KINDS[module], id=binding.resource_id),
                    )
                    for tool in _human_tools(module)
                )
            ).model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )
