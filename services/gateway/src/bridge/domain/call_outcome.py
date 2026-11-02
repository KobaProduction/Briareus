"""A missing complete reply never proves that an MCP effect succeeded."""

from dataclasses import dataclass
from typing import Literal

CallOutcome = Literal["failed", "unknown", "completed"]


@dataclass(frozen=True, slots=True)
class ReplyFacts:
    has_result: bool
    reported_error: bool
    effect_error: bool


@dataclass(frozen=True, slots=True)
class CallObservation:
    status: int
    complete: bool
    reply: ReplyFacts | None


def call_outcome(observation: CallObservation) -> CallOutcome:
    if observation.status >= 400:
        return "failed"
    if not observation.complete or observation.reply is None:
        return "unknown"
    if observation.reply.has_result:
        return "failed" if observation.reply.effect_error else "completed"
    return "failed" if observation.reply.reported_error else "unknown"
