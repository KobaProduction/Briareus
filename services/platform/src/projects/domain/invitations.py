"""Inviter grants do not confer operator or team membership authority."""

from dataclasses import dataclass
from uuid import UUID

from projects.domain.management import ManagementError


@dataclass(frozen=True, slots=True)
class InvitationEmail:
    value: str

    @classmethod
    def parse(cls, value: object) -> "InvitationEmail":
        if not isinstance(value, str) or not 3 <= len(value) <= 254 or value.count("@") != 1:
            raise ManagementError(422, "EMAIL_INVALID")
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ManagementError(422, "EMAIL_INVALID")
        return cls(value.lower())


@dataclass(frozen=True, slots=True)
class InvitationCapabilities:
    can_invite: bool
    can_manage_inviters: bool
    inviter_ids: tuple[UUID, ...]
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class InviterOutcome:
    id: UUID
    enabled: bool
    state: str = "committed"


@dataclass(frozen=True, slots=True)
class InvitationOutcome:
    id: str
    state: str = "provider_created"
    delivery: str = "unconfirmed"


@dataclass(frozen=True, slots=True)
class ProviderUser:
    subject: str


InvitationResult = InviterOutcome | InvitationOutcome
