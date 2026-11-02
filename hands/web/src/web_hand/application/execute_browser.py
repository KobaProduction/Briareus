"""Controls precede profile changes; only authorized status renews startup."""

from typing import Protocol

from hand_runtime.domain.deferred_operations import OperationAuthority
from service_runtime.runtime_binding import _RuntimeBinding
from web_hand.application.prepare_profile import ProfileReadiness
from web_hand.domain.execution import BrowserAction, BrowserIntent
from web_hand.domain.profile import LeaseIdentity


class BrowserExecution[Outcome](Protocol):
    async def operation_control(
        self,
        identity: LeaseIdentity,
    ) -> Outcome: ...
    def operation_running(self) -> bool: ...
    def pending_status(self, identity: LeaseIdentity) -> Outcome: ...
    async def prepare_execution(
        self, profile_key: str, identity: LeaseIdentity
    ) -> ProfileReadiness: ...
    def startup_pending(self) -> bool: ...
    def startup_complete(self) -> bool: ...
    def starting(self) -> Outcome: ...
    async def operation_start(
        self,
        identity: LeaseIdentity,
    ) -> Outcome: ...
    async def grant_execution(self, identity: LeaseIdentity, expires_at: float) -> None: ...
    async def authorized_status(self) -> Outcome: ...
    async def exchange(self) -> Outcome: ...


class ExecuteBrowser[Outcome](_RuntimeBinding[BrowserExecution[Outcome]]):
    async def execute(
        self,
        intent: BrowserIntent,
        authority: OperationAuthority,
        profile_key: str,
    ) -> Outcome:
        identity = authority.identity
        if intent.action is BrowserAction.CONTROL_OPERATION:
            return await self.runtime.operation_control(identity)
        if self.runtime.operation_running():
            if intent.action is BrowserAction.STATUS and intent.empty_arguments:
                return self.runtime.pending_status(identity)
            raise ValueError("Web operation in progress; poll or cancel it first")
        readiness = await self.runtime.prepare_execution(profile_key, identity)
        if readiness is not ProfileReadiness.READY:
            return self._preparing(intent, readiness)
        if self.runtime.startup_pending() and intent.action is not BrowserAction.STATUS:
            raise ValueError("Browser is starting; poll local_browser_status first")
        if intent.action is BrowserAction.START_OPERATION:
            return await self.runtime.operation_start(identity)
        await self.runtime.grant_execution(identity, authority.expires_at)
        if intent.action is BrowserAction.STATUS:
            # Even a warm Chromium inspection may outlive one short effect lease.
            # Subsequent authorized polls renew the same process and status task.
            return await self.runtime.authorized_status()
        return await self.runtime.exchange()

    def _preparing(
        self,
        intent: BrowserIntent,
        readiness: ProfileReadiness,
    ) -> Outcome:
        if intent.action is BrowserAction.STATUS and intent.empty_arguments:
            return self.runtime.starting()
        if readiness is ProfileReadiness.SESSION_PREPARING:
            raise ValueError("Clean browser session preparing; poll local_browser_status")
        raise ValueError("Browser metadata preparing; poll local_browser_status")
