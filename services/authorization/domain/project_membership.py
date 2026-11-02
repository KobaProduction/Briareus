"""Minimal current Platform membership proof consumed by Authorization.

A verified Rauthy subject and current Project membership MUST originate from
a separate authenticated owner request, never an incoming MCP header.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from authorization.domain.decisions import DecisionAuthorityUnavailable, DecisionScopeDenied


@dataclass(frozen=True, slots=True)
class MembershipSelector:
    issuer: str
    subject: str
    project_uuid: UUID

    @classmethod
    def checked(cls, issuer: object, subject: object, project_uuid: object) -> MembershipSelector:
        if not isinstance(issuer, str) or not issuer.startswith("https://"):
            raise DecisionScopeDenied("invalid Platform membership selector")
        if not isinstance(subject, str) or not 1 <= len(subject) <= 256:
            raise DecisionScopeDenied("invalid Platform membership selector")
        if not isinstance(project_uuid, UUID) or project_uuid.version != 4:
            raise DecisionScopeDenied("invalid Platform membership selector")
        return cls(issuer, subject, project_uuid)


@dataclass(frozen=True, slots=True)
class MembershipDelegationScope:
    selector: MembershipSelector
    audience: str
    expires_at: datetime

    def require_current(self, expected: MembershipSelector, now: datetime) -> None:
        if self.selector != expected or self.audience != "briareus:platform":
            raise DecisionScopeDenied("Platform delegated subject/project proof invalid")
        if self.expires_at.tzinfo is None or not now < self.expires_at <= now + timedelta(
            seconds=30
        ):
            raise DecisionScopeDenied("Platform delegated subject/project proof invalid")


def verify_delegation_credential(credential: str) -> None:
    if not 40 <= len(credential) <= 8192 or not credential.isascii():
        raise DecisionAuthorityUnavailable("signed Platform service bearer invalid")
    if any(char.isspace() for char in credential):
        raise DecisionAuthorityUnavailable("signed Platform service bearer invalid")


@dataclass(frozen=True, slots=True)
class VerifiedProjectMembership:
    rauthy_issuer: str
    rauthy_subject: str
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime

    def require_owner_match(
        self,
        selector: MembershipSelector,
        delegation_expiry: datetime,
        now: datetime,
    ) -> None:
        actual = MembershipSelector(self.rauthy_issuer, self.rauthy_subject, self.project_uuid)
        if actual != selector or self.actor_uuid.version != 4 or self.project_uuid.version != 4:
            raise DecisionScopeDenied("Platform membership mismatch or expired")
        if self.expires_at.tzinfo is None or not now < self.expires_at <= delegation_expiry:
            raise DecisionScopeDenied("Platform membership mismatch or expired")
