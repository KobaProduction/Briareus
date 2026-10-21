"""Human Terminal facade; private owner calls, never the live MCP dataplane."""

from datetime import UTC, datetime
import logging
import time
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from runtime_peer import PeerClient

from ._oidc_approvals import (
    OwnerManagementConflict, OwnerManagementDenied, OwnerManagementInvalidInput,
    OwnerManagementNotFound, OwnerManagementUnavailable,
)
from ._oidc_membership import CurrentPlatformContext
from ._oidc_origin_policy import BROWSER_ORIGIN
from ._runtime_access_client import RuntimeAccessClient
from ._panel_events import panel_events

_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class TerminalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    expected_grant_revision: int = Field(strict=True, ge=1)
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict[str, object] = Field(max_length=16)

    @field_validator("operation_uuid", "project_uuid", "agent_session_uuid")
    @classmethod
    def v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Canonical project, session and operation UUIDs required")
        return value


def terminal_runtime_router(*, current_context: CurrentPlatformContext,
                             access: RuntimeAccessClient, terminal: PeerClient,
                             files: PeerClient | None = None, web: PeerClient | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runtime")

    def fail(status: int, code: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code}}, status_code=status, headers=_HEADERS)

    def owner_error(error: Exception) -> JSONResponse:
        if isinstance(error, OwnerManagementDenied):
            return fail(403, "RUNTIME_PERMISSION_DENIED")
        if isinstance(error, OwnerManagementConflict):
            return fail(409, "RUNTIME_REVISION_CONFLICT")
        if isinstance(error, OwnerManagementInvalidInput):
            return fail(422, "RUNTIME_SCOPE_INVALID")
        if isinstance(error, OwnerManagementNotFound):
            return fail(404, "RUNTIME_NOT_FOUND")
        return fail(503, "RUNTIME_OWNER_UNAVAILABLE")

    @router.get("/resources")
    async def resources(request: Request, project_uuid: UUID,
                        hand: Literal["terminal", "files", "web"] = "terminal") -> JSONResponse:
        context = await current_context(request, project_uuid)
        if isinstance(context, JSONResponse):
            return context
        _, proof = context
        try:
            body = await access.for_actor(proof)._call("resource.list", proof.user_uuid, project_uuid, {"hand": hand})
            return JSONResponse(body, headers=_HEADERS)
        except Exception as error:
            return owner_error(error)

    @router.post("/terminal/call")
    async def terminal_call(request: Request) -> JSONResponse:
        return await call(request, "terminal")

    @router.post("/files/call")
    async def files_call(request: Request) -> JSONResponse:
        return await call(request, "files")

    @router.post("/web/call")
    async def web_call(request: Request) -> JSONResponse:
        return await call(request, "web")

    async def call(request: Request, hand: str) -> JSONResponse:
        peer = {"terminal": terminal, "files": files, "web": web}[hand]
        if peer is None:
            return fail(503, "RUNTIME_OWNER_UNAVAILABLE")
        if (request.headers.getlist("origin") != [BROWSER_ORIGIN]
            or request.headers.getlist("content-type") != ["application/json"]
            or request.headers.get("sec-fetch-site") not in (None, "same-origin")):
            return fail(403, "RUNTIME_ORIGIN_REQUIRED")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 32_768:
                return fail(413, "RUNTIME_COMMAND_TOO_LARGE")
        try:
            command = TerminalCommand.model_validate_json(body)
        except ValidationError:
            return fail(422, "RUNTIME_COMMAND_INVALID")
        if hand == "terminal" and command.tool == "terminal_exec":
            seconds = command.arguments.get("timeout_seconds")
            if type(seconds) not in (int, float) or not 0 < seconds <= 3:
                return fail(422, "TERMINAL_QUICK_COMMAND_LIMIT")
        context = await current_context(request, command.project_uuid)
        if isinstance(context, JSONResponse):
            return context
        session, proof = context
        payload = {
            "tool": command.tool, "arguments": command.arguments,
            "agent_session_uuid": str(command.agent_session_uuid),
            "expected_grant_revision": command.expected_grant_revision,
            "operation_uuid": str(command.operation_uuid),
        }
        began = time.monotonic()
        started = False
        async def report(status):
            await panel_events.publish(actor=proof.user_uuid, project=command.project_uuid, hand=hand,
                tool=command.tool if started else "unverified", operation=command.operation_uuid,
                status=status, duration_ms=round((time.monotonic()-began)*1000))
        try:
            permit = await access.for_actor(proof)._call(
                hand + ".prepare", proof.user_uuid, command.project_uuid, payload,
            )
            started = True
            await report("started")
            status, result = await peer.call("/internal/v1/" + hand + "/call", {
                "permit": permit["permit"], "tool": command.tool, "arguments": command.arguments,
            })
            if status != 200 or "result" not in result:
                logging.getLogger(__name__).warning("terminal owner reply status=%d result_present=%s",
                                                    status, "result" in result)
                await report("unknown")
                return fail(503, hand.upper() + "_OUTCOME_UNKNOWN")
            # Recheck membership and the durable Cedar grant after the effect,
            # before returning project output. Revoked scopes release no bytes.
            current = await current_context(request, command.project_uuid)
            if isinstance(current, JSONResponse):
                await report("unknown")
                return current
            current_session, current_proof = current
            if (current_session.subject != session.subject or current_proof.user_uuid != proof.user_uuid
                or min(current_session.expires_at, current_proof.expires_at) <= datetime.now(UTC)):
                await report("unknown")
                return fail(403, "RUNTIME_ACTOR_CHANGED")
            await access.for_actor(current_proof)._call(
                hand + ".prepare", proof.user_uuid, command.project_uuid, payload,
            )
            tool_result = result["result"]
            failed = isinstance(tool_result, dict) and (tool_result.get("isError") is True or tool_result.get("is_error") is True)
            await report("failed" if failed else "completed")
            return JSONResponse({"operation_uuid": str(command.operation_uuid), "result": result["result"]},
                                 headers=_HEADERS)
        except Exception as error:
            await report("unknown" if started else "denied")
            return owner_error(error)

    return router
