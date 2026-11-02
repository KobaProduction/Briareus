"""Analysis adds engine ownership to the shared bounded operation index."""

from dataclasses import dataclass
from uuid import UUID

from hand_runtime.domain.deferred_operations import OperationHandle, OperationIndex, OperationState
from hand_runtime.process_lease_domain import LeaseIdentity

from .dispatch import Engine


@dataclass(slots=True)
class AnalysisOperation:
    operation_id: OperationHandle
    identity: LeaseIdentity
    engine: Engine
    tool: str
    state: OperationState = OperationState.RUNNING

    def require_owner(self, identity: LeaseIdentity) -> None:
        if self.identity != identity:
            raise ValueError("Analysis operation unavailable for this identity")

    def interrupt(self) -> bool:
        if self.state != OperationState.RUNNING:
            return False
        self.state = OperationState.INTERRUPTED
        return True

    def finish(self, *, failed: bool) -> bool:
        if self.state != OperationState.RUNNING:
            return False
        self.state = OperationState.FAILED if failed else OperationState.COMPLETED
        return True


class OperationInventory(OperationIndex[AnalysisOperation]):
    def owned(self, token: OperationHandle, identity: LeaseIdentity) -> AnalysisOperation:
        record = self.lookup(token)
        if record is None:
            raise ValueError("Analysis operation unavailable for this identity")
        record.require_owner(identity)
        return record

    def require_idle(self) -> None:
        if self.running():
            raise ValueError("Analysis operation in progress; poll or cancel it first")

    def add(
        self, request_uuid: UUID, identity: LeaseIdentity, engine: Engine, tool: str
    ) -> AnalysisOperation:
        self.require_idle()
        record = AnalysisOperation(self.allocate(request_uuid), identity, engine, tool)
        self.insert(record)
        return record
