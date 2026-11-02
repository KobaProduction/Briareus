"""Bounded browser input and exact public connection responses."""

from fastapi import Request
from fastapi.responses import JSONResponse

from control_panel_api._oidc_origin_policy import BROWSER_ORIGIN
from control_panel_api.application.connections import (
    ConnectionFailure,
    ConnectionInput,
    ManageConnections,
)
from control_panel_api.infrastructure.connections import HttpConnectionAuthority
from control_panel_api.presentation._http_errors import error_response

from ._bindings import _ControllerServiceBinding
from ._request_body import browser_command

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


connection_failure = error_response


async def connection_input(request: Request) -> ConnectionInput | JSONResponse:
    return await browser_command(
        request,
        ConnectionInput,
        origin=BROWSER_ORIGIN,
        maximum_bytes=60000,
        origin_code="CONNECTION_ORIGIN_REQUIRED",
        size_code="CONNECTION_INPUT_TOO_LARGE",
        invalid_code="CONNECTION_INPUT_INVALID",
    )


class ConnectionsController(_ControllerServiceBinding[ManageConnections, HttpConnectionAuthority]):
    async def command(self, request: Request) -> JSONResponse:
        value = await connection_input(request)
        if isinstance(value, JSONResponse):
            return value
        result = await self._service.execute(value)
        if self._authority.rejection is not None:
            return self._authority.rejection
        if isinstance(result, ConnectionFailure):
            return connection_failure(result.status, result.code)
        return JSONResponse(
            result.model_dump(mode="json", by_alias=True, exclude_unset=True), headers=HEADERS
        )
