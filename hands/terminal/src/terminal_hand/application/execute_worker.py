"""Execute one private command; the supervisor retains authority ownership."""

from typing import Protocol

from runtime_peer.terminal_receipts import TerminalReceipt
from terminal_hand.application.worker_contracts import WorkerOutcome
from terminal_hand.domain.worker_command import WorkerToolPolicy


class WorkerDispatch(Protocol):
    async def execute(self) -> TerminalReceipt: ...


class ExecuteWorkerCommand:
    def __init__(self, dispatch: WorkerDispatch, tools: frozenset[str]) -> None:
        self._dispatch = dispatch
        self._policy = WorkerToolPolicy(tools)

    async def execute(self, tool: str) -> WorkerOutcome:
        self._policy.require_available(tool)
        try:
            result = await self._dispatch.execute()
        except Exception:
            return WorkerOutcome(error="TERMINAL_OPERATION_FAILED")
        return WorkerOutcome(result=result)
