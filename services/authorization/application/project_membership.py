"""Resolve independent current Platform membership through a delegated owner port."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import SecretStr

from authorization.application._reference_bindings import _OwnerBinding
from authorization.domain.project_membership import (
    MembershipDelegationScope,
    MembershipSelector,
    VerifiedProjectMembership,
    verify_delegation_credential,
)


@dataclass(frozen=True, slots=True)
class VerifiedPlatformMembershipDelegation:
    bearer: SecretStr
    issuer: str
    subject: str
    project_uuid: UUID
    audience: Literal["briareus:platform"]
    expires_at: datetime

    def scope(self) -> MembershipDelegationScope:
        return MembershipDelegationScope(
            MembershipSelector(self.issuer, self.subject, self.project_uuid),
            self.audience,
            self.expires_at,
        )


class PlatformMembershipOwner(Protocol):
    async def delegate(
        self, selector: MembershipSelector
    ) -> VerifiedPlatformMembershipDelegation: ...

    async def member(
        self,
        selector: MembershipSelector,
        delegation: VerifiedPlatformMembershipDelegation,
    ) -> VerifiedProjectMembership: ...


class ResolveCurrentProjectMembership(_OwnerBinding[PlatformMembershipOwner]):
    async def execute(self, selector: MembershipSelector) -> VerifiedProjectMembership:
        delegation = await self._owner.delegate(selector)
        delegation.scope().require_current(selector, datetime.now(UTC))
        verify_delegation_credential(delegation.bearer.get_secret_value())
        member = await self._owner.member(selector, delegation)
        member.require_owner_match(selector, delegation.expires_at, datetime.now(UTC))
        return member
