"""Execute once through Platform owner and require current authority after its reply."""

from datetime import UTC, datetime
from typing import Protocol

from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_management import (
    ManagementCommand,
    ManagementErrorBody,
    ManagementIntent,
    ManagementOutput,
    ManagementReceipt,
    RpcFailure,
)


class ManagementOwner(Protocol):
    async def execute(
        self, context: PanelContext, command: ManagementCommand, expires_at: datetime
    ) -> ManagementReceipt: ...


class ManagementAuthority(Protocol):
    async def current(self) -> PanelContext | None: ...


class PlatformRpc:
    def __init__(self, authority: ManagementAuthority, owner: ManagementOwner | None) -> None:
        self._authority = authority
        self._owner = owner

    async def execute(self, intent: ManagementIntent) -> ManagementOutput:
        current = await self._authority.current()
        if current is None:
            raise RpcFailure("CURRENT_PLATFORM_REQUIRED")
        intent.authorize(current)
        if self._owner is None:
            raise RpcFailure("PLATFORM_MANAGEMENT_UNAVAILABLE")
        deadline = min(current.session.expires_at, current.proof.expires_at)
        try:
            receipt = await self._owner.execute(current, intent.command, deadline)
        except Exception:
            raise RpcFailure("OPERATION_OUTCOME_UNKNOWN", uncertain=intent.mutation) from None
        if receipt.status != 200 or isinstance(receipt.result, ManagementErrorBody):
            code = (
                receipt.result.error.code
                if isinstance(receipt.result, ManagementErrorBody)
                else "PLATFORM_MANAGEMENT_UNAVAILABLE"
            )
            raise RpcFailure(
                code if len(code) <= 128 else "UNAVAILABLE",
                uncertain=intent.mutation
                and receipt.status >= 500
                and code
                not in {
                    "RAUTHY_INVITATION_MAIL_UNCONFIGURED",
                    "RAUTHY_INVITATION_KEY_UNAVAILABLE",
                },
            )
        fresh = await self._authority.current()
        if (
            fresh is None
            or deadline <= datetime.now(UTC)
            or not intent.authority_continues(fresh, current)
        ):
            raise RpcFailure("OPERATION_OUTCOME_UNKNOWN", uncertain=intent.mutation)
        return receipt.result
