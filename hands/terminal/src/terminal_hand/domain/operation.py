"""Replay identity for a single Terminal effect."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class OperationIdentity:
    operation_uuid: UUID
    fingerprint: str

    def require_fingerprint(self, stored: str) -> None:
        if stored != self.fingerprint:
            raise ValueError("Terminal operation identity reused with changed arguments")


def require_history_capacity(count: int) -> None:
    if count >= 10_000:
        raise ValueError("Terminal operation history capacity reached")
