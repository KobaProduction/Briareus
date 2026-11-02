"""HTTP connection callbacks adapted to framework-independent channel authority."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import WebSocket
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from starlette.requests import HTTPConnection

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api.application.panel_channel import ContextUnavailable, RpcFault, RpcValue
from control_panel_api.application.platform_projection import PlatformContextPayload
from control_panel_api.domain.panel_protocol import PanelContext


class CurrentPanelUser(Protocol):
    async def __call__(
        self,
        request: HTTPConnection,
        project_uuid: UUID | None = None,
    ) -> JSONResponse: ...


@dataclass(frozen=True, slots=True)
class PanelAuthorityAdapter:
    socket: WebSocket
    current_context: CurrentPlatformContext
    current_user: CurrentPanelUser

    async def current(self, project: UUID | None = None) -> PanelContext | ContextUnavailable:
        context = await self.current_context(self.socket, project)
        if isinstance(context, JSONResponse):
            return ContextUnavailable(context.status_code)
        return PanelContext(*context)

    async def user(self, project: UUID | None) -> RpcValue[PlatformContextPayload] | RpcFault:
        response = await self.current_user(self.socket, project)
        if response.status_code != 200:
            return RpcFault("Current Platform context unavailable")
        value = TypeAdapter(PlatformContextPayload).validate_json(bytes(response.body))
        return RpcValue(value)
