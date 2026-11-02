"""Bounded same-origin human runtime commands and public response serialization."""

from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from mcp_types import CallToolResult

from control_panel_api._oidc_origin_policy import BROWSER_ORIGIN
from control_panel_api.application.runtime_effect import HumanRuntimeEffects, RuntimeFailure
from control_panel_api.application.runtime_effect_contracts import (
    RuntimeEffectResult,
    RuntimeHand,
    TerminalCommand,
)
from control_panel_api.infrastructure.runtime_effect import HttpRuntimeAuthority
from control_panel_api.infrastructure.runtime_replies import LegacyRuntimeReply, NativeRuntimeReply
from control_panel_api.presentation._http_errors import error_response
from runtime_peer.runtime_resource_receipts import RuntimeResources

from ._bindings import _ControllerServiceBinding
from ._request_body import browser_command

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


runtime_failure = error_response


async def runtime_input(request: Request) -> TerminalCommand | JSONResponse:
    return await browser_command(
        request,
        TerminalCommand,
        origin=BROWSER_ORIGIN,
        maximum_bytes=32768,
        origin_code="RUNTIME_ORIGIN_REQUIRED",
        size_code="RUNTIME_COMMAND_TOO_LARGE",
        invalid_code="RUNTIME_COMMAND_INVALID",
    )


class RuntimeController(
    _ControllerServiceBinding[HumanRuntimeEffects[NativeRuntimeReply], HttpRuntimeAuthority]
):
    async def call(self, request: Request, hand: RuntimeHand) -> JSONResponse:
        command = await runtime_input(request)
        if isinstance(command, JSONResponse):
            return command
        return self._response(await self._service.execute(command, hand))

    async def resources(self, project: UUID, hand: RuntimeHand) -> JSONResponse:
        return self._response(await self._service.resources(project, hand))

    def _response(
        self,
        result: RuntimeResources | RuntimeEffectResult[NativeRuntimeReply] | RuntimeFailure,
    ) -> JSONResponse:
        if self._authority.rejection is not None:
            return self._authority.rejection
        if isinstance(result, RuntimeFailure):
            return runtime_failure(result.status, result.code)
        if isinstance(result, RuntimeEffectResult) and isinstance(
            result.result, LegacyRuntimeReply
        ):
            legacy = result.result
            encoded = legacy.sdk.model_dump(mode="json", by_alias=True, exclude_unset=True)
            if not legacy.camel_error_present:
                encoded.pop("isError", None)
            encoded["is_error"] = legacy.is_error
            return JSONResponse(
                {"operation_uuid": str(result.operation_uuid), "result": encoded}, headers=HEADERS
            )
        return JSONResponse(
            result.model_dump(
                mode="json",
                exclude_unset=True,
                by_alias=isinstance(result, RuntimeEffectResult)
                and isinstance(result.result, CallToolResult),
            ),
            headers=HEADERS,
        )
