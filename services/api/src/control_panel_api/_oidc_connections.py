"""Cookie-authenticated, write-only credential entry into the Resources owner."""
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from ._oidc_origin_policy import BROWSER_ORIGIN
from ._panel_events import panel_events

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_uuid: UUID
    action: Literal["forms", "list", "verify", "create", "update", "delete", "check"]
    connection_uuid: UUID | None = None
    alias: str = Field(default="", max_length=128)
    credential: SecretStr = Field(default=SecretStr(""))
    configuration: dict[str, object] = Field(default_factory=dict, max_length=12)
    expected_revision: int | None = Field(default=None, strict=True, ge=1)
    cursor: str | None = Field(default=None, max_length=1024)


def connection_router(*, current_context, peer):
    router = APIRouter()

    def fail(status, code):
        return JSONResponse({"error": {"code": code}}, status_code=status, headers=HEADERS)

    @router.post("/api/v1/connections")
    async def command(request: Request):
        if (request.headers.getlist("origin") != [BROWSER_ORIGIN]
            or request.headers.getlist("content-type") != ["application/json"]
            or request.headers.get("sec-fetch-site") not in {None, "same-origin"}):
            return fail(403, "CONNECTION_ORIGIN_REQUIRED")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 60000:
                return fail(413, "CONNECTION_INPUT_TOO_LARGE")
        try:
            value = ConnectionInput.model_validate_json(body)
        except ValidationError:
            return fail(422, "CONNECTION_INPUT_INVALID")
        context = await current_context(request, value.project_uuid)
        if isinstance(context, JSONResponse):
            return context
        session, proof = context
        if proof.role != "operator":
            return fail(403, "CONNECTION_OPERATOR_REQUIRED")
        if peer is None:
            return fail(503, "CONNECTION_OWNER_UNAVAILABLE")
        data = value.model_dump(mode="json", exclude={"credential"})
        data.update(credential=value.credential.get_secret_value(), issuer=proof.issuer,
                    subject=proof.subject, actor_uuid=str(proof.user_uuid),
                    identity_expires_at=min(session.expires_at, proof.expires_at).isoformat())
        try:
            status, result = await peer.call("/internal/v1/resources/connections", data)
        except Exception:
            return fail(503, "CONNECTION_OWNER_UNAVAILABLE")
        if status != 200:
            return fail(status if status in {403, 404, 409, 422} else 503, {
                403: "CONNECTION_PERMISSION_DENIED", 404: "CONNECTION_NOT_FOUND",
                409: "CONNECTION_ALREADY_EXISTS", 422: "CONNECTION_INPUT_INVALID",
            }.get(status, "CONNECTION_OWNER_UNAVAILABLE"))
        current = await current_context(request, value.project_uuid)
        if isinstance(current, JSONResponse):
            return current
        fresh_session, fresh = current
        if (fresh.user_uuid != proof.user_uuid or fresh_session.subject != session.subject
            or fresh.role != "operator" or min(fresh.expires_at, fresh_session.expires_at) <= datetime.now(UTC)):
            return fail(403, "CONNECTION_ACTOR_CHANGED")
        if value.action in {"create", "update", "delete"}:
            await panel_events.emit("management.events", "connection." + value.action, {
                "project_id": str(value.project_uuid), "connection_id": str(value.connection_uuid),
                "actor_id": str(proof.user_uuid)}, visibility={"kind": "project", "id": str(value.project_uuid)})
        return JSONResponse(result, headers=HEADERS)

    return router
