"""Private read sequence; no output escapes an expired signed effect."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from files_hand.application.private_receipts import PrivateFileResult
from files_hand.domain.private_effect import PrivateEffectBinding, PrivateFilesDecision
from files_hand.domain.private_read import PrivateFileQuery


class PrivateDecisionVerifier(Protocol):
    def verify(self, token: str) -> PrivateFilesDecision: ...


class PrivateFileExecutor(Protocol):
    def execute(self, query: PrivateFileQuery) -> PrivateFileResult: ...


class WallClock(Protocol):
    def now(self) -> float: ...


@dataclass(frozen=True, slots=True)
class PrivateFilesOutcome:
    operation_uuid: UUID
    result: PrivateFileResult


class ExecutePrivateFiles:
    def __init__(
        self,
        verifier: PrivateDecisionVerifier,
        files: PrivateFileExecutor,
        clock: WallClock,
        tools: frozenset[str],
    ) -> None:
        self._verifier = verifier
        self._files = files
        self._clock = clock
        self._tools = tools

    def execute(
        self, token: str, binding: PrivateEffectBinding, query: PrivateFileQuery
    ) -> PrivateFilesOutcome:
        decision = self._verifier.verify(token)
        if binding.tool not in self._tools or binding.tool != query.tool:
            raise ValueError("Effect binding mismatch")
        decision.require_binding(binding)
        result = self._files.execute(query)
        decision.require_output_authority(self._clock.now())
        return PrivateFilesOutcome(decision.facts.operation_uuid, result)
