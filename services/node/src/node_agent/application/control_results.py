"""Framework-independent results of the admitted node control use cases."""

from dataclasses import dataclass
from uuid import UUID

from node_protocol.domain.observations import FailureFacts, NodeFailure, NodeOperation, NodeReply
from node_protocol.journal import JournalOperation


@dataclass(frozen=True, slots=True)
class ControlResult:
    status: int
    payload: NodeReply


def reject(status: int, code: str) -> ControlResult:
    return ControlResult(status, NodeFailure(code))


def operation_payload(row: JournalOperation) -> NodeOperation:
    value = row.diagnostic
    diagnostic = (
        None
        if value is None
        else FailureFacts(
            value.stage,
            value.component,
            value.reason,
            value.exit_code,
            value.health_status,
            value.oom_killed,
            value.health_exit_code,
        )
    )
    return NodeOperation(UUID(row.id), row.sequence, row.phase, row.error, diagnostic)
