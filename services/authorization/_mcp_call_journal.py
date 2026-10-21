"""Gateway transport outcomes bound to actual Authorization-issued effects.

This records metadata only. A journal receipt never grants execution rights.
"""
import base64
import time
from typing import Literal

from cryptography.exceptions import InvalidSignature
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import insert

from node_protocol.effect import NodeEffectPermit
from node_protocol.files import strict_json
from ._platform_persistence import OutboxRow, SecurityAuditRow


class CallOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permit: str = Field(min_length=1, max_length=8192)
    status: Literal["completed", "failed", "unknown"]
    duration_ms: int = Field(strict=True, ge=0, le=86400000)


def verified_call(encoded, key):
    envelope = strict_json(base64.b64decode(encoded, validate=True))
    if not isinstance(envelope, dict) or set(envelope) != {"permit", "signature"}:
        raise ValueError("Exact effect receipt required")
    permit = NodeEffectPermit.model_validate(envelope["permit"])
    key.verify(base64.b64decode(envelope["signature"], validate=True), permit.signing_bytes())
    # An expired execution permit is evidence of a past call, never authority
    # to resume it. Bound delayed delivery and reject future/fabricated effects.
    if (permit.method != "tools/call" or not permit.tool
        or not 0 < permit.expires_at - permit.issued_at <= 5
        or not time.time() - 86400 < permit.issued_at <= time.time() + 2):
        raise ValueError("Recent actual tool call required")
    return permit


def mcp_call_journal_router(*, resolve_database, signing_key):
    router = APIRouter()

    @router.post("/internal/v1/authorization/mcp-call-outcome", include_in_schema=False)
    async def record(command: CallOutcome, request: Request):
        if request.scope.get("briareus.service_peer") != "briareus:gateway":
            raise HTTPException(403, "Gateway peer required")
        database = resolve_database()
        if database is None or signing_key is None:
            raise HTTPException(503, "Journal unavailable")
        try:
            permit = verified_call(command.permit, signing_key.public_key())
        except (ValueError, KeyError, TypeError, InvalidSignature):
            raise HTTPException(403, "Actual effect evidence required") from None
        event = "mcp.call." + command.status
        metadata = {"hand": permit.module, "tool": permit.tool, "status": command.status,
            "session_uuid": str(permit.agent_session_uuid), "node_uuid": str(permit.node_uuid),
            "placement_uuid": str(permit.placement_uuid), "duration_ms": command.duration_ms,
            "transport": "gateway-mcp"}
        async with database.transaction() as tx:
            created = await tx.execute(insert(SecurityAuditRow).values(id=permit.request_uuid,
                actor_id=permit.actor_uuid, project_id=permit.project_uuid, action=event,
                object_id=str(permit.agent_session_uuid),
                details={"operation_uuid": str(permit.request_uuid), "call": metadata})
                .on_conflict_do_nothing(index_elements=[SecurityAuditRow.id])
                .returning(SecurityAuditRow.id))
            if created.scalar_one_or_none() is not None:
                tx.add(OutboxRow(id=permit.request_uuid, event_name=event, event_payload={
                    "operation_uuid": str(permit.request_uuid), "project_id": str(permit.project_uuid),
                    "entity_id": str(permit.agent_session_uuid)}))
        return {"recorded": True}

    return router
