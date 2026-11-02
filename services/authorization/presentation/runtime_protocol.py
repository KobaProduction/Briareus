"""Private signed-runtime HTTP DTOs and final JSON serialization."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from authorization.application.event_receipts import EventPageResponse as RuntimeEvents
from authorization.application.runtime_dispatch import (
    RuntimeApprovals,
    RuntimePermit,
    RuntimeResult,
    RuntimeSessions,
    RuntimeWriteReceipt,
)
from authorization.application.runtime_inputs import COMMAND_TYPES, RuntimeAction, RuntimeCommand
from authorization.presentation.runtime_effect import decode_runtime_effect
from authorization.presentation.session_reads import approval_response, session_response
from runtime_peer.access_management_wire import RuntimeHumanIdentity
from runtime_peer.runtime_resource_receipts import RuntimeResources


class ActorContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime
    permissions: tuple[Literal["use_resources", "approve_agent_session"], ...]
    role: Literal["user", "operator"]


class RuntimeAccessCommand(RuntimeHumanIdentity):
    action: RuntimeAction
    command: RuntimeCommand

    @field_validator("command", mode="before")
    @classmethod
    def parse_command(cls, value: object, info: ValidationInfo[object]) -> RuntimeCommand:
        action: object = info.data.get("action")
        if not isinstance(action, str):
            raise ValueError("Known runtime action required")
        if action in {"terminal.prepare", "files.prepare", "web.prepare"}:
            return decode_runtime_effect(value)
        try:
            model = COMMAND_TYPES[action]
        except (KeyError, TypeError):
            raise ValueError("Known runtime action required") from None
        if isinstance(value, model):
            return value
        if not isinstance(value, dict) or len(value) > 12:
            raise ValueError("Bounded runtime command object required")
        payload: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Runtime command keys must be strings")
            payload[key] = item
        if action in {
            "session.open",
            "session.revoke",
            "session.request_elevation",
            "session.resolve_elevation",
            "session.list",
            "session.get",
            "approval.list",
        }:
            project_uuid: object = info.data.get("project_uuid")
            if not isinstance(project_uuid, UUID):
                raise ValueError("Runtime project selector required")
            payload["project_uuid"] = project_uuid
        return model.model_validate(payload)


def runtime_response(result: RuntimeResult) -> JSONResponse:
    if isinstance(result, RuntimeSessions):
        if result.detail:
            if not result.items:
                return JSONResponse({"error": {"code": "NOT_FOUND"}}, status_code=404)
            return JSONResponse({"item": session_response(result.items[0]).model_dump(mode="json")})
        return JSONResponse(
            {"items": [session_response(item).model_dump(mode="json") for item in result.items]}
        )
    if isinstance(result, RuntimeApprovals):
        return JSONResponse(
            {"items": [approval_response(item).model_dump(mode="json") for item in result.items]}
        )
    if isinstance(result, RuntimeWriteReceipt):
        return JSONResponse(result.body.model_dump(mode="json"), status_code=result.status)
    if isinstance(result, RuntimePermit):
        return JSONResponse({"permit": result.permit})
    if isinstance(result, RuntimeResources):
        return JSONResponse(result.model_dump(mode="json", by_alias=True, exclude_none=True))
    if isinstance(result, RuntimeEvents):
        return JSONResponse(result.model_dump(mode="json", by_alias=True))
    raise TypeError("Unsupported typed runtime result")
