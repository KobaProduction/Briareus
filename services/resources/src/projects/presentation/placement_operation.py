"""Public placement operation response, separate from persistence and signed receipts."""

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from node_protocol.diagnostics import FailureDiagnostic
from projects.domain.placement_recovery import (
    PlacementReconciliationBusy,
    require_reconciliation_capacity,
)


class PlacementOperationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str
    placement_uuid: str
    sequence: int
    phase: str
    error: str | None
    updated_at: str
    diagnostic: FailureDiagnostic | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    reconciliation_required: bool | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    restored: bool | None = Field(default=None, exclude_if=lambda value: value is None)


def placement_operation_response(operation: PlacementOperationSummary) -> JSONResponse:
    return JSONResponse(
        {
            "operation": operation.model_dump(mode="json", exclude_none=True)
            | {"error": operation.error}
        }
    )


def require_placement_capacity(active: int) -> None:
    try:
        require_reconciliation_capacity(active)
    except PlacementReconciliationBusy as exc:
        raise HTTPException(429, str(exc)) from None
