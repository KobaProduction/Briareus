"""Provider status controls role sync; Platform suspension is never undone."""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from projects.domain.context import current_expiry
from projects.domain.membership import CurrentRauthyUserLink, PlatformSubjectLinkUnavailable

PlatformRole = Literal["user", "operator"]
ProvisioningAction = Literal["panel.user.provisioned", "panel.user.provider_role_changed"]
RAUTHY_SUBJECT_PATTERN = re.compile(r"[A-Za-z0-9]{24}\Z", flags=re.ASCII)


def canonical_subject(value: object) -> bool:
    return isinstance(value, str) and RAUTHY_SUBJECT_PATTERN.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class VerifiedRauthyUserStatus:
    issuer: str
    subject: str
    active: bool
    expires_at: datetime
    name: str | None = None
    email: str | None = None
    role: PlatformRole = "user"


def verify_status(
    value: object, issuer: str, subject: str, now: datetime
) -> VerifiedRauthyUserStatus:
    if not isinstance(value, VerifiedRauthyUserStatus):
        raise PlatformSubjectLinkUnavailable("upstream User status not current")
    if value.issuer != issuer or value.subject != subject or type(value.active) is not bool:
        raise PlatformSubjectLinkUnavailable("upstream User status identity invalid")
    if value.role not in {"user", "operator"} or not current_expiry(value.expires_at, now):
        raise PlatformSubjectLinkUnavailable("upstream User status not current")
    return value


@dataclass(slots=True)
class PlatformUserLink:
    uuid: UUID
    issuer: str
    subject: str
    role: PlatformRole
    active: bool
    revision: int
    created_at: datetime
    updated_at: datetime

    def sync_role(self, role: PlatformRole, now: datetime) -> ProvisioningAction | None:
        if self.role == role:
            return None
        self.role = role
        self.revision += 1
        self.updated_at = now
        return "panel.user.provider_role_changed"

    def current(self, status: VerifiedRauthyUserStatus) -> CurrentRauthyUserLink:
        if self.uuid.version != 4 or self.revision < 1 or self.role not in {"user", "operator"}:
            raise PlatformSubjectLinkUnavailable("Platform user link invalid")
        return CurrentRauthyUserLink(
            self.issuer,
            self.subject,
            self.uuid,
            self.active,
            self.role,
            self.revision,
            status.expires_at,
            status.name,
            status.email,
        )
