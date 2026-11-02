"""Existing fsync/exclusive-marker/atomic-replace outcome journal."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from web_hand.domain.dispatch import (
    DispatchIdentity,
    DispatchReservation,
    require_history_capacity,
    require_same_effect,
)
from web_hand.infrastructure.browser_ipc import BrowserReply


class SavedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str
    result: BrowserReply | None = None


@dataclass(slots=True)
class FileOutcomeJournal:
    root: Path

    def reserve(self, identity: DispatchIdentity) -> DispatchReservation[BrowserReply]:
        target = self.root / f"{identity.operation}.json"
        if target.exists():
            saved = SavedOutcome.model_validate_json(target.read_bytes())
            require_same_effect(saved.fingerprint, identity.fingerprint)
            return DispatchReservation(
                True, saved.result or BrowserReply(error="WEB_OUTCOME_UNKNOWN")
            )
        require_history_capacity(len(list(self.root.glob("*.json"))))
        self._write(target, SavedOutcome(fingerprint=identity.fingerprint))
        return DispatchReservation(False, BrowserReply(error="WEB_OUTCOME_UNKNOWN"))

    def commit(self, identity: DispatchIdentity, outcome: BrowserReply) -> None:
        target = self.root / f"{identity.operation}.json"
        temporary = target.with_suffix(".pending")
        self._write(temporary, SavedOutcome(fingerprint=identity.fingerprint, result=outcome))
        temporary.replace(target)

    @staticmethod
    def _write(target: Path, saved: SavedOutcome) -> None:
        with target.open("x") as handle:
            os.chmod(target, 0o600)
            json.dump(saved.model_dump(mode="json", by_alias=True, exclude_unset=True), handle)
            handle.flush()
            os.fsync(handle.fileno())
