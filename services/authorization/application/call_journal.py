"""Record one audit/outbox fact for a verified effect request."""

import time
from dataclasses import dataclass
from typing import Protocol

from authorization.domain.call_journal import CallEvidence, CallJournalEntry


class CallEvidencePort(Protocol):
    def verify(self, encoded: str) -> CallEvidence: ...


class CallJournalRepositoryPort(Protocol):
    async def record_once(self, entry: CallJournalEntry) -> None: ...


@dataclass(frozen=True, slots=True)
class CallRecorded:
    recorded: bool


class RecordCallOutcome:
    def __init__(self, verifier: CallEvidencePort, repository: CallJournalRepositoryPort) -> None:
        self.verifier = verifier
        self.repository = repository

    async def execute(self, *, permit: str, status: str, duration_ms: int) -> CallRecorded:
        evidence = self.verifier.verify(permit)
        evidence.require_recent_call(time.time())
        entry = CallJournalEntry(evidence, status, duration_ms)
        entry.require_valid()
        await self.repository.record_once(entry)
        return CallRecorded(True)
