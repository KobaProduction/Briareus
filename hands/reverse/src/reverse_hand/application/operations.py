"""Owned poll/cancel renewals never replay the original engine effect."""

from typing import Protocol

from hand_runtime.domain.deferred_operations import OperationAuthority as OperationAuthority
from hand_runtime.domain.deferred_operations import OperationHandle, OperationState
from hand_runtime.process_lease_domain import LeaseIdentity
from reverse_hand.domain.operations import AnalysisOperation, OperationInventory
from service_runtime.runtime_binding import _RuntimeBinding


class OperationRuntime(Protocol):
    def ready(self) -> bool: ...
    def lease_identity(self) -> LeaseIdentity | None: ...
    async def renew(self, authority: OperationAuthority) -> bool: ...
    async def stop(self) -> None: ...
    def schedule_recovery(self) -> None: ...


class AnalysisPreparing(ValueError):
    """A fresh native runtime must be prepared before a caller can issue an effect."""


class AdmitAnalysisExecution(_RuntimeBinding[OperationRuntime]):
    async def execute(self, authority: OperationAuthority, now: float) -> None:
        if authority.expires_at <= now:
            raise ValueError("Current analysis execution authority required")
        if not self.runtime.ready():
            raise AnalysisPreparing
        prior = self.runtime.lease_identity()
        preserved = await self.runtime.renew(authority)
        if prior is not None and not preserved:
            raise AnalysisPreparing


class PollAnalysisOperation:
    def __init__(self, inventory: OperationInventory, runtime: OperationRuntime) -> None:
        self.inventory = inventory
        self.runtime = runtime

    async def execute(
        self, token: OperationHandle, authority: OperationAuthority, *, cancel: bool, now: float
    ) -> AnalysisOperation:
        if authority.expires_at <= now:
            raise ValueError("Current owned analysis operation required")
        # Ownership is resolved before any process lease can be touched.
        record = self.inventory.owned(token, authority.identity)
        if record.state != OperationState.RUNNING:
            return record
        if cancel:
            await self.runtime.stop()
            record.state = OperationState.CANCELLED
            self.runtime.schedule_recovery()
            return record
        if not self.runtime.ready() or self.runtime.lease_identity() != authority.identity:
            raise ValueError("Original prepared analysis runtime required")
        await self.runtime.renew(authority)
        return record
