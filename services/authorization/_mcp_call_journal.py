"""Gateway-only HTTP boundary for verified historical MCP call outcomes."""

from collections.abc import Callable
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from authorization.application.call_journal import RecordCallOutcome
from authorization.infrastructure.call_journal import SignedCallEvidence, SqlCallJournal
from authorization.infrastructure.call_journal import verified_call as verified_call
from common.platform_db import PlatformDatabase


class CallOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    permit: str = Field(min_length=1, max_length=8192)
    status: Literal["completed", "failed", "unknown"]
    duration_ms: int = Field(strict=True, ge=0, le=86400000)


class CallJournalController:
    def __init__(
        self,
        resolve_database: Callable[[], PlatformDatabase | None],
        signing_key: Ed25519PrivateKey | None,
    ) -> None:
        self.resolve_database = resolve_database
        self.signing_key = signing_key

    async def record(self, command: CallOutcome, request: Request) -> JSONResponse:
        if request.scope.get("briareus.service_peer") != "briareus:gateway":
            raise HTTPException(403, "Gateway peer required")
        database = self.resolve_database()
        if database is None or self.signing_key is None:
            raise HTTPException(503, "Journal unavailable")
        use_case = RecordCallOutcome(
            SignedCallEvidence(self.signing_key.public_key()), SqlCallJournal(database)
        )
        try:
            result = await use_case.execute(
                permit=command.permit, status=command.status, duration_ms=command.duration_ms
            )
        except (ValueError, KeyError, TypeError, InvalidSignature):
            raise HTTPException(403, "Actual effect evidence required") from None
        return JSONResponse({"recorded": result.recorded})


def mcp_call_journal_router(
    *,
    resolve_database: Callable[[], PlatformDatabase | None],
    signing_key: Ed25519PrivateKey | None,
) -> APIRouter:
    router = APIRouter()
    controller = CallJournalController(resolve_database, signing_key)
    router.add_api_route(
        "/internal/v1/authorization/mcp-call-outcome",
        controller.record,
        methods=["POST"],
        include_in_schema=False,
    )
    return router
