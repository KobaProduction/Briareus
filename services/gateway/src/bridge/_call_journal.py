"""Decode transport reply observations and adapt the streaming completion callback."""

import json

from gateway_runtime.stream import StreamCompletion
from node_protocol.json_boundary import request_identity

from .application.call_outcome import CallOutcomePort, RecordCallOutcome
from .domain.call_outcome import CallObservation, CallOutcome, ReplyFacts, call_outcome
from .infrastructure.admission import TrustedGatewayDecisionPort

type CallObserver = StreamCompletion


def reply_facts(body: bytes | None) -> ReplyFacts | None:
    if body is None:
        return None
    try:
        frames: list[object] = [
            json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith(b"data:")
        ]
        value: object = frames[-1] if frames else json.loads(body)
        if not isinstance(value, dict):
            return ReplyFacts(False, False, False)
        result: object = value.get("result")
        has_result = isinstance(result, dict)
        effect_error = isinstance(result, dict) and result.get("isError") is True
        return ReplyFacts(has_result, "error" in value, effect_error)
    except (ValueError, TypeError):
        return None


def outcome(status: int, body: bytes | None, complete: bool) -> CallOutcome:
    return call_outcome(observation(status, body, complete))


def observation(status: int, body: bytes | None, complete: bool) -> CallObservation:
    facts = reply_facts(body) if status < 400 and complete else None
    return CallObservation(status, complete, facts)


def observer(authority: CallOutcomePort, permit: str, *, started: float) -> CallObserver:
    use_case = RecordCallOutcome(authority)

    async def record(status: int, body: bytes | None, complete: bool) -> None:
        await use_case.execute(permit, observation(status, body, complete), started)

    return record


def optional_observer(
    authority: TrustedGatewayDecisionPort | CallOutcomePort | None,
    body: bytes,
    permit: str,
    *,
    started: float,
) -> CallObserver | None:
    frame = request_identity(body)
    if frame.method == "tools/call" and isinstance(authority, CallOutcomePort):
        return observer(authority, permit, started=started)
    return None
