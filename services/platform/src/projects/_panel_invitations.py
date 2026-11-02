"""Compose the invitation saga behind the existing authenticated Panel contract."""

from datetime import UTC, datetime
from typing import Protocol

from common.platform_db import PlatformDatabase
from projects._oidc_membership_projection import CurrentRauthyPlatformMembership
from projects.application.invitations import (
    InvitationActor,
    InvitationCommand,
    InvitationIdentity,
    IssueInvitation,
    ManageInvitations,
    SetInviter,
)
from projects.domain.invitations import (
    InvitationCapabilities,
    InvitationEmail,
    InvitationResult,
)
from projects.domain.management import identifier
from projects.infrastructure.invitation_provider import (
    InvitationLookupTransport,
    RauthyInvitationProvider,
    create_provider_user,
    provisioning_error,
)
from projects.infrastructure.invitations import (
    InvitationProjection,
    ProjectionInvitationAuthority,
    SqlInvitationUnitOfWork,
)
from projects.presentation.management_inputs import (
    InvitationCapabilitiesQuery,
    InvitationQuery,
    IssueInvitationQuery,
    SetInviterQuery,
)

__all__ = ["create_provider_user", "execute_invitations", "provisioning_error"]


class InvitationService(Protocol):
    @property
    def db(self) -> PlatformDatabase: ...

    @property
    def projection(self) -> InvitationProjection: ...

    @property
    def provider(self) -> InvitationLookupTransport: ...


def invitation_change(
    query: SetInviterQuery | IssueInvitationQuery,
) -> SetInviter | IssueInvitation:
    if isinstance(query, SetInviterQuery):
        return SetInviter(identifier(query.data.user_id), query.data.enabled)
    return IssueInvitation(InvitationEmail.parse(query.data.email))


async def execute_invitations(
    service: InvitationService,
    query: InvitationQuery,
    actor: CurrentRauthyPlatformMembership,
    deadline: datetime,
) -> InvitationCapabilities | InvitationResult:
    use_case = ManageInvitations(
        SqlInvitationUnitOfWork(service.db),
        RauthyInvitationProvider(service.provider),
        ProjectionInvitationAuthority(service.projection),
        lambda: datetime.now(UTC),
    )
    identity = InvitationIdentity(query.issuer, query.subject)
    inviter = InvitationActor(actor.user_id, actor.role == "operator")
    if isinstance(query, InvitationCapabilitiesQuery):
        return await use_case.capabilities(identity, inviter)
    command = InvitationCommand(
        identity,
        inviter,
        query.operation_uuid,
        query.fingerprint(),
        invitation_change(query),
    )
    return await use_case.execute(command, deadline)
