"""HTTP request bounds and serialization for typed Platform management use cases."""

from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import RootModel

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api.application.platform_management import HumanPlatformManagement
from control_panel_api.domain.management_operations import ReadInventory
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_management import (
    ManagementCommand,
    ManagementErrorBody,
    ManagementOutput,
)

from ._request_body import browser_command
from .platform_commands import PlatformCommand

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class ManagementResponse(RootModel[ManagementOutput | ManagementErrorBody]):
    """The existing flat owner response, with UUIDs encoded only at HTTP output."""


class PlatformManagementController:
    def __init__(
        self, current: CurrentPlatformContext, management: HumanPlatformManagement, *, origin: str
    ) -> None:
        self._current = current
        self._management = management
        self._origin = origin

    async def _invoke(self, request: Request, command: ManagementCommand) -> JSONResponse:
        context = await self._current(request)
        if isinstance(context, JSONResponse):
            return context
        result = await self._management.invoke(PanelContext(*context), command)
        body = ManagementResponse(root=result.result).model_dump(mode="json")
        return JSONResponse(body, status_code=result.status, headers=HEADERS)

    async def inventory(self, request: Request) -> JSONResponse:
        return await self._invoke(request, ManagementCommand(uuid4(), ReadInventory()))

    async def command(self, request: Request) -> JSONResponse:
        parsed = await browser_command(
            request,
            PlatformCommand,
            origin=self._origin,
            maximum_bytes=8192,
            origin_code="PLATFORM_ORIGIN_REQUIRED",
            size_code="COMMAND_TOO_LARGE",
            invalid_code="COMMAND_INVALID",
        )
        if isinstance(parsed, JSONResponse):
            return parsed
        return await self._invoke(request, parsed.command())
