"""One-app Watch Paths reconciliation; the port cannot enumerate or recreate apps."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from watch_sync_domain import ApprovedWatchTarget, SavedWatchMetadata, SyncError


class WatchConfiguration(Protocol):
    def read(self) -> SavedWatchMetadata: ...

    def replace_watch_paths(self, value: str) -> None: ...


class SyncState(StrEnum):
    ALREADY_SYNCHRONIZED = "already_synchronized"
    DIFFERENT = "different"
    SYNCHRONIZED = "synchronized"


@dataclass(frozen=True)
class SyncResult:
    state: SyncState


class SyncWatchPaths:
    def __init__(self, configuration: WatchConfiguration) -> None:
        self._configuration = configuration

    def execute(self, target: ApprovedWatchTarget, *, apply: bool) -> SyncResult:
        current = self._configuration.read()
        current.require_target(target)
        if current.watch_paths == target.watch_value:
            return SyncResult(SyncState.ALREADY_SYNCHRONIZED)
        if not apply:
            return SyncResult(SyncState.DIFFERENT)
        # Never retry an uncertain write. The operator must inspect its outcome.
        self._configuration.replace_watch_paths(target.watch_value)
        verified = self._configuration.read()
        verified.require_target(target)
        if verified.watch_paths != target.watch_value:
            raise SyncError(
                "Coolify did not persist exact watch_paths; outcome requires inspection"
            )
        return SyncResult(SyncState.SYNCHRONIZED)
