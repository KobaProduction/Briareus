"""Plan a signed receipt projection before changing owner persistence."""

from dataclasses import dataclass

from projects.domain.placement_reconciliation import (
    TERMINAL_PHASES,
    OperationReceipt,
    OperationState,
)


@dataclass(frozen=True)
class ReconciliationDecision:
    terminal: bool
    update_operation: bool
    placement_state: str | None
    apply_desired_release: bool
    restore_limits: bool
    audit: bool


def reconcile_receipt(
    operation: OperationState,
    receipt: OperationReceipt,
    *,
    placement_sequence: int,
    restoration_verified: bool,
    restoration_changes_projection: bool,
    diagnostic_changed: bool,
    first_diagnostic: bool,
) -> ReconciliationDecision:
    receipt.validate_for(operation, placement_sequence)
    if operation.phase in TERMINAL_PHASES:
        return ReconciliationDecision(
            True,
            False,
            "ready" if restoration_changes_projection else None,
            False,
            restoration_changes_projection,
            restoration_changes_projection or first_diagnostic,
        )
    state = "updating"
    if receipt.phase == "succeeded" or restoration_verified:
        state = "ready"
    elif receipt.phase == "failed":
        state = "failed"
    changed = (operation.phase, operation.error) != (
        receipt.phase,
        receipt.error,
    ) or diagnostic_changed
    return ReconciliationDecision(
        receipt.phase in TERMINAL_PHASES,
        True,
        state,
        receipt.phase == "succeeded",
        restoration_verified,
        changed,
    )
