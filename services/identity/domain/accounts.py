"""Legacy account credential revisions and last administrator protection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from identity._domain import UserRole


class LastAdministrator(ValueError):
    pass


@dataclass(frozen=True)
class AccountSnapshot:
    user_id: UUID
    username: str
    role: UserRole
    enabled: bool
    credential_version: int
    password_digest: str

    def with_password(self, digest: str) -> AccountSnapshot:
        return replace(self, password_digest=digest, credential_version=self.credential_version + 1)

    def with_superuser(self, enabled: bool, active_superusers: int) -> AccountSnapshot:
        if self.role == "superuser" and not enabled and active_superusers <= 1:
            raise LastAdministrator("cannot demote the last active superuser")
        return replace(
            self,
            role=UserRole.SUPERUSER if enabled else UserRole.USER,
            credential_version=self.credential_version + 1,
        )

    def with_suspension(self, suspend: bool, active_superusers: int) -> AccountSnapshot:
        if suspend and self.enabled and self.role == "superuser" and active_superusers <= 1:
            raise LastAdministrator("cannot suspend the last active superuser")
        return replace(
            self,
            enabled=not suspend,
            credential_version=self.credential_version + 1,
        )


@dataclass(frozen=True)
class PasswordResetState:
    kind: str
    used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None
    target_id: UUID | None
    issuer_id: UUID | None

    def available(self, now: datetime) -> bool:
        return (
            self.kind == "password_reset"
            and self.used_at is None
            and self.revoked_at is None
            and self.expires_at is not None
            and self.expires_at > now
            and self.target_id is not None
        )
