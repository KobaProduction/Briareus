"""Rotating refresh send intent is durable and never replayed after an uncertain send."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .native_login import SecretText


@dataclass(frozen=True, slots=True)
class RefreshSnapshot:
    version: str = field(repr=False)
    issuer: str
    client_id: str
    subject: str
    expires_at: datetime
    hard_deadline: datetime
    token: SecretText | None = field(repr=False)
    not_before: datetime | None
    attempted: bool

    def remaining(self, now: datetime) -> int:
        return max(1, int((self.hard_deadline - now).total_seconds()))

    def is_current(self, issuer: str, client_id: str, now: datetime) -> bool:
        return (
            self.hard_deadline > now
            and self.issuer.rstrip("/") == issuer
            and self.client_id == client_id
            and self.token is not None
        )

    def renewal_due(self, now: datetime) -> bool:
        if self.not_before is None:
            return False
        return now >= max(self.expires_at - timedelta(seconds=45), self.not_before)
