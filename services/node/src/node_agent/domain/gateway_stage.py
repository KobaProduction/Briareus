"""Only an owned existing Gateway may be resumed or replaced."""

from dataclasses import dataclass

from .worker_stage import WorkerStageFailure


@dataclass(frozen=True, slots=True)
class GatewayCandidate:
    identity: str
    owned: bool
    fingerprint: str
    running: bool


def gateway_candidate(rows: tuple[GatewayCandidate, ...]) -> GatewayCandidate | None:
    if len(rows) > 1 or any(not row.owned for row in rows):
        raise WorkerStageFailure("Refusing to adopt a foreign Gateway container")
    return rows[0] if rows else None
