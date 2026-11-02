"""Replace only an attested target; journal phases surround every native effect."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from node_agent.domain.placement import (
    TERMINAL_PHASES,
    OperationConflict,
    validate_placement_owner,
)
from node_agent.planner import Instance, Plan, plan
from node_protocol import Deployment, NodeRecord
from node_protocol.diagnostics import FailureDiagnostic


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    sequence: int
    phase: str
    previous: Deployment | None
    container: str | None
    diagnostic: FailureDiagnostic | None


class RuntimeFailure(RuntimeError):
    def __init__(self, diagnostic: FailureDiagnostic | None, reason: str | None) -> None:
        super().__init__("Placement execution failed")
        self.diagnostic, self.reason = diagnostic, reason


class OperationStore(Protocol):
    async def reserve(
        self, operation: UUID, sequence: int, desired: Deployment
    ) -> OperationSnapshot: ...

    async def current(self, operation: UUID) -> OperationSnapshot: ...

    async def phase(
        self,
        operation: UUID,
        phase: str,
        *,
        container: str | None = None,
        error: str | None = None,
        diagnostic: FailureDiagnostic | None = None,
    ) -> None: ...

    async def applied(self, operation: UUID, desired: Deployment, container: str) -> None: ...

    async def restore(self, operation: UUID, previous: Deployment, container: str) -> None: ...

    async def matches_applied(self, desired: Deployment, container: str) -> bool: ...

    async def failed_candidate(
        self, desired: Deployment, container: str, fingerprint: str, sequence: int
    ) -> bool: ...


class PlacementRuntime(Protocol):
    async def verify_rootless(self) -> None: ...

    async def observed(self) -> list[Instance]: ...

    async def resume_applied(self, desired: Deployment) -> str: ...

    async def wait_ready(self, container: str) -> None: ...

    async def pull(self, desired: Deployment) -> None: ...

    async def remove_target(self, desired: Deployment, container: str) -> None: ...

    async def stage(self, desired: Deployment) -> str: ...

    async def diagnose(
        self, receipt: OperationSnapshot, desired: Deployment, *, deadline_expired: bool
    ) -> FailureDiagnostic: ...


@dataclass(frozen=True, slots=True)
class ReplacementSelection:
    plan: Plan
    targets: tuple[Instance, ...]
    matching: tuple[Instance, ...]
    failed_candidate: bool


def validate_admission(node: NodeRecord, desired: Deployment) -> None:
    if desired.node_uuid != node.id or not node.enabled or not desired.enabled:
        raise OperationConflict("Enabled placement on the exact enrolled node required")


class ApplyPlacement:
    def __init__(
        self, node: Callable[[], NodeRecord], store: OperationStore, runtime: PlacementRuntime
    ) -> None:
        self._node, self._store, self._runtime = node, store, runtime

    async def execute(self, operation: UUID, sequence: int, desired: Deployment) -> None:
        # The caller holds the shared configuration/capacity lock. Re-read the
        # node after acquiring it, because admission may have been disabled.
        if not self._node().enabled:
            raise OperationConflict("Node admission was disabled while waiting")
        receipt = await self._store.reserve(operation, sequence, desired)
        if receipt.phase in TERMINAL_PHASES:
            return
        previous = receipt.previous
        if previous is not None:
            validate_placement_owner(
                previous.project_uuid,
                desired.project_uuid,
                previous.workspace.id if previous.workspace else None,
                desired.workspace.id if desired.workspace else None,
            )
        if receipt.phase == "rolling_back":
            await self.rollback(operation, previous, desired)
            return
        try:
            await self._apply(operation, sequence, desired, receipt)
        except (RuntimeFailure, TimeoutError) as failure:
            await self._failed(operation, desired, previous, failure)

    async def _apply(
        self, operation: UUID, sequence: int, desired: Deployment, receipt: OperationSnapshot
    ) -> None:
        await self._runtime.verify_rootless()
        observed = await self._runtime.observed()
        if await self._repair_applied(operation, desired, observed):
            return
        selected = await self._select(sequence, desired, observed)
        if selected.plan.action == "keep":
            await self._store.applied(operation, desired, selected.targets[0].container_id)
            return
        recovering = (
            receipt.phase in {"creating", "checking"}
            and len(selected.targets) == len(selected.matching) == 1
            and selected.matching[0].running
        )
        if selected.plan.action in {"blocked", "disabled"} and not recovering:
            raise RuntimeFailure(None, None)
        if self._unmanaged(receipt, selected, recovering):
            await self._store.phase(operation, "failed", error="UNMANAGED_INSTANCE")
            return
        container = await self._target_container(operation, desired, selected)
        await self._store.phase(operation, "checking", container=container)
        await self._runtime.wait_ready(container)
        await self._store.applied(operation, desired, container)

    async def _repair_applied(
        self, operation: UUID, desired: Deployment, observed: list[Instance]
    ) -> bool:
        own = [item for item in observed if item.deployment_uuid == desired.id]
        if not (
            len(own) == 1
            and not own[0].ready
            and own[0].fingerprint == desired.fingerprint
            and own[0].limits == desired.limits
            and await self._store.matches_applied(desired, own[0].container_id)
            and self._node().budget.fits([item.limits for item in observed])
        ):
            return False
        # Only an explicit fresh Core operation repairs a journaled applied
        # instance. A label alone never attests a foreign/failed process.
        await self._store.phase(operation, "checking", container=own[0].container_id)
        container = await self._runtime.resume_applied(desired)
        await self._runtime.wait_ready(container)
        await self._store.applied(operation, desired, container)
        return True

    async def _select(
        self, sequence: int, desired: Deployment, observed: list[Instance]
    ) -> ReplacementSelection:
        action = plan(self._node(), desired, observed)
        targets = tuple(item for item in observed if item.deployment_uuid == desired.id)
        matching = tuple(item for item in targets if item.fingerprint == desired.fingerprint)
        failed = len(targets) == 1 and await self._store.failed_candidate(
            desired, targets[0].container_id, targets[0].fingerprint, sequence
        )
        if action.action == "blocked" and failed and not targets[0].ready:
            # A fresh operation may replace its own journaled failed candidate.
            # Unknown processes remain blocked even when labels match.
            action = plan(self._node(), desired, [item for item in observed if item not in targets])
            matching = ()
        return ReplacementSelection(action, targets, matching, failed)

    @staticmethod
    def _unmanaged(
        receipt: OperationSnapshot, selected: ReplacementSelection, recovering: bool
    ) -> bool:
        return bool(
            selected.targets
            and receipt.previous is None
            and not selected.failed_candidate
            and not (recovering and receipt.container == selected.targets[0].container_id)
        )

    async def _target_container(
        self, operation: UUID, desired: Deployment, selected: ReplacementSelection
    ) -> str:
        if selected.matching:
            # Lost create/start acknowledgements resume readiness without
            # stopping a matching process or replaying its MCP effects.
            return selected.matching[0].container_id
        await self._store.phase(operation, "pulling")
        await self._runtime.pull(desired)
        await self._store.phase(operation, "stopping")
        for item in selected.targets:
            await self._runtime.remove_target(desired, item.container_id)
        await self._store.phase(operation, "creating")
        return await self._runtime.stage(desired)

    async def _failed(
        self,
        operation: UUID,
        desired: Deployment,
        previous: Deployment | None,
        failure: RuntimeFailure | TimeoutError,
    ) -> None:
        receipt = await self._store.current(operation)
        diagnostic = failure.diagnostic if isinstance(failure, RuntimeFailure) else None
        if diagnostic is None and isinstance(failure, RuntimeFailure) and failure.reason:
            diagnostic = FailureDiagnostic.model_validate(
                {
                    "stage": receipt.phase,
                    "component": "engine",
                    "reason": failure.reason,
                }
            )
        if diagnostic is None:
            diagnostic = await self._runtime.diagnose(
                receipt, desired, deadline_expired=isinstance(failure, TimeoutError)
            )
        await self._store.phase(operation, receipt.phase, diagnostic=diagnostic)
        await self.rollback(operation, previous, desired)

    async def rollback(
        self, operation: UUID, previous: Deployment | None, desired: Deployment
    ) -> None:
        receipt = await self._store.current(operation)
        if receipt.phase in {"queued", "pulling"} or previous is None:
            await self._store.phase(operation, "failed", error="UPDATE_FAILED")
            return
        await self._store.phase(operation, "rolling_back", error="UPDATE_FAILED")
        try:
            current = [
                item
                for item in await self._runtime.observed()
                if item.deployment_uuid == desired.id
            ]
            if len(current) > 1:
                raise RuntimeFailure(None, None)
            if current and current[0].fingerprint != previous.fingerprint:
                await self._runtime.remove_target(desired, current[0].container_id)
            container = await self._runtime.stage(previous)
            await self._runtime.wait_ready(container)
            await self._store.restore(operation, previous, container)
            # Restoring prior execution does not turn the requested update
            # into a success. Its terminal receipt remains failed.
            await self._store.phase(operation, "failed", container=container, error="UPDATE_FAILED")
        except (RuntimeFailure, TimeoutError):
            await self._store.phase(operation, "failed", error="ROLLBACK_FAILED")
