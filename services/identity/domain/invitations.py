"""Legacy invitation revocation ownership and consumption invariants."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class InvitationPermissionDenied(ValueError):
    pass


class InvitationAlreadyUsed(ValueError):
    pass


@dataclass(frozen=True)
class RevocableInvitation:
    invitation_id: UUID
    issuer_id: UUID | None
    used_at: datetime | None
    revoked_at: datetime | None

    def require_revocation(self, actor_id: UUID, *, superuser: bool) -> bool:
        if self.issuer_id != actor_id and not superuser:
            raise InvitationPermissionDenied("invitation issuer or superuser required")
        if self.used_at is not None:
            raise InvitationAlreadyUsed("cannot revoke an already used invitation")
        return self.revoked_at is None
