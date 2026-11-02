"""Protected legacy invitation and first administrator registration invariants."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from identity._domain import UserRole


class RegistrationDenied(ValueError):
    pass


@dataclass(frozen=True)
class RegistrationInvitationState:
    kind: str
    expires_at: datetime | None
    used_at: datetime | None
    revoked_at: datetime | None
    issuer_id: UUID | None

    def require_available(self, now: datetime, *, preflight: bool = False) -> None:
        if self.kind not in {"system", "registration"}:
            raise RegistrationDenied("invitation is invalid or unavailable")
        if self.used_at is not None or self.revoked_at is not None:
            message = (
                "invitation is invalid or unavailable"
                if preflight
                else "invitation is no longer valid"
            )
            raise RegistrationDenied(message)
        if self.expires_at is not None and self.expires_at <= now:
            message = (
                "invitation is invalid or unavailable" if preflight else "invitation has expired"
            )
            raise RegistrationDenied(message)

    def registration_role(self, *, first_superuser_claimed: bool) -> UserRole:
        if not first_superuser_claimed and self.kind != "system":
            raise RegistrationDenied("first administrator requires the protected setup code")
        if first_superuser_claimed and self.kind == "system":
            raise RegistrationDenied("initial administrator setup is permanently closed")
        return UserRole.USER if first_superuser_claimed else UserRole.SUPERUSER


def require_password_length(password: str) -> None:
    if not 12 <= len(password) <= 4096:
        raise ValueError("password must be between 12 and 4096 characters")
