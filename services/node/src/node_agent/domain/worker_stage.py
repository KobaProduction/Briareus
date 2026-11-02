"""A stopped or foreign candidate cannot become an implicit replacement."""

from dataclasses import dataclass


class WorkerStageFailure(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class WorkerCandidate:
    identity: str
    owned: bool
    stopped: bool


def select_candidate(
    candidates: tuple[WorkerCandidate, ...], *, resume_stopped: bool
) -> WorkerCandidate | None:
    if not candidates:
        return None
    if len(candidates) != 1 or not candidates[0].owned:
        raise WorkerStageFailure("Conflicting candidate; refusing adoption")
    candidate = candidates[0]
    if candidate.stopped and not resume_stopped:
        raise WorkerStageFailure("Candidate stopped; explicit recovery required")
    return candidate
