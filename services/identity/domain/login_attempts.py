"""Legacy source and identity login throttle state transitions."""

from dataclasses import dataclass
from datetime import datetime, timedelta


class LoginBlocked(ValueError):
    pass


@dataclass
class LoginAttemptState:
    key: str
    failures: int
    last_failed_at: datetime | None
    blocked_until: datetime | None

    def prepare(self, now: datetime) -> None:
        if self.blocked_until is not None and self.blocked_until > now:
            raise LoginBlocked("too many login attempts")
        if self.last_failed_at is not None and now - self.last_failed_at > timedelta(minutes=10):
            self.failures = 0

    def fail(self, now: datetime, *, limit: int) -> None:
        self.failures += 1
        self.last_failed_at = now
        if self.failures >= limit:
            multiplier = 2 ** min(self.failures - limit, 4)
            self.blocked_until = now + timedelta(seconds=min(300, 30 * multiplier))

    def succeed(self) -> None:
        self.failures = 0
        self.blocked_until = None
