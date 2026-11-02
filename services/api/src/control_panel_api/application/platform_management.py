"""Cookie-bound human management preserves the Platform owner's commit authority."""

from datetime import UTC, datetime
from typing import Protocol

from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_management import (
    ManagementCommand,
    ManagementErrorBody,
    ManagementReceipt,
    OwnerError,
)
from control_panel_api.domain.realtime_payloads import PlatformMutation as ManagementCommitted

from .platform_rpc import ManagementOwner


class ManagementEvents(Protocol):
    async def committed(self, event: ManagementCommitted) -> None: ...


def management_failure(status: int, code: str) -> ManagementReceipt:
    return ManagementReceipt(status, ManagementErrorBody(OwnerError(code)))


class HumanPlatformManagement:
    def __init__(self, owner: ManagementOwner | None, events: ManagementEvents) -> None:
        self._owner = owner
        self._events = events

    async def invoke(self, context: PanelContext, command: ManagementCommand) -> ManagementReceipt:
        if context.proof.role != "operator" and command.action not in {
            "invitation.capabilities",
            "invitation.issue",
        }:
            return management_failure(403, "PLATFORM_OPERATOR_REQUIRED")
        if self._owner is None:
            return management_failure(503, "PLATFORM_MANAGEMENT_UNAVAILABLE")
        deadline = min(context.session.expires_at, context.proof.expires_at)
        if deadline <= datetime.now(UTC):
            return management_failure(401, "OIDC_SESSION_EXPIRED")
        try:
            receipt = await self._owner.execute(context, command, deadline)
            if deadline <= datetime.now(UTC):
                return management_failure(503, "OPERATION_OUTCOME_UNKNOWN")
            if receipt.status not in {200, 401, 403, 404, 409, 413, 422, 503}:
                return management_failure(503, "PLATFORM_MANAGEMENT_UNAVAILABLE")
            if receipt.status == 200 and command.action != "inventory":
                await self._events.committed(
                    ManagementCommitted(
                        command.action,
                        command.operation_uuid,
                        context.proof.user_uuid,
                    )
                )
            return receipt
        except Exception:
            return management_failure(503, "OPERATION_OUTCOME_UNKNOWN")
