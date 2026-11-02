"""Bind one verified MCP request to the browser lifecycle's inward execution port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp.types import CallToolRequestParams

from node_protocol.effect import EffectPermit
from web_hand.application.prepare_profile import ProfileReadiness
from web_hand.domain.execution import BrowserAction, BrowserIntent
from web_hand.domain.profile import LeaseIdentity

from .browser_ipc import BrowserReply

if TYPE_CHECKING:
    from web_hand.node_supervisor import WebSupervisor


def browser_intent(call: CallToolRequestParams) -> BrowserIntent:
    actions = {
        "web_operation_poll": BrowserAction.CONTROL_OPERATION,
        "web_operation_cancel": BrowserAction.CONTROL_OPERATION,
        "web_operation_start": BrowserAction.START_OPERATION,
        "local_browser_status": BrowserAction.STATUS,
    }
    return BrowserIntent(actions.get(call.name, BrowserAction.CALL), not call.arguments)


@dataclass(frozen=True, slots=True)
class BoundBrowserExecution:
    runtime: WebSupervisor
    call: CallToolRequestParams
    permit: EffectPermit

    async def operation_control(self, identity: LeaseIdentity) -> BrowserReply:
        return await self.runtime.operation_control(self.call, self.permit, identity)

    def operation_running(self) -> bool:
        return self.runtime.operation_running()

    def pending_status(self, identity: LeaseIdentity) -> BrowserReply:
        return self.runtime.pending_status(identity, self.permit)

    async def prepare_execution(
        self, profile_key: str, identity: LeaseIdentity
    ) -> ProfileReadiness:
        return await self.runtime.prepare_execution(profile_key, identity)

    def startup_pending(self) -> bool:
        return self.runtime.startup_pending()

    def startup_complete(self) -> bool:
        return self.runtime.startup_complete()

    def starting(self) -> BrowserReply:
        return self.runtime.starting(self.permit)

    async def operation_start(self, identity: LeaseIdentity) -> BrowserReply:
        return await self.runtime.operation_start(self.call, self.permit, identity)

    async def grant_execution(self, identity: LeaseIdentity, expires_at: float) -> None:
        await self.runtime.grant_execution(identity, expires_at)

    async def authorized_status(self) -> BrowserReply:
        return await self.runtime.authorized_status(self.call, self.permit)

    async def exchange(self) -> BrowserReply:
        return await self.runtime.exchange(self.call, self.permit)
