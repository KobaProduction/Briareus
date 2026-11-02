"""Durable acknowledgement requires ownership of the current outbox claim."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ClaimedEvent:
    """A committed event's identity and content binding, independent of its schema."""

    event_id: UUID
    claim_id: UUID
    event_name: str
    content_sha256: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256):
            raise ValueError("Canonical committed-event digest required")


@dataclass(frozen=True, slots=True)
class OutboxSettlement:
    published_at: datetime | None
    locked_until: datetime | None
    acknowledged: bool


@dataclass(frozen=True, slots=True)
class OutboxDeliveryState:
    claim_uuid: UUID | None
    published_at: datetime | None
    attempts: int

    def settle(
        self, claim_uuid: UUID, acknowledged: bool, now: datetime
    ) -> OutboxSettlement | None:
        if self.claim_uuid != claim_uuid or self.published_at is not None:
            return None
        if acknowledged:
            return OutboxSettlement(now, None, True)
        delay = min(300, 2 ** min(self.attempts, 8))
        return OutboxSettlement(None, now + timedelta(seconds=delay), False)


def require_outbox_limit(limit: int) -> None:
    if not 1 <= limit <= 256:
        raise ValueError("outbox batch limit must be between 1 and 256")
