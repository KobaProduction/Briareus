"""Legacy Authorization collaborators bound to the caller's existing SQL transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from authorization.infrastructure.journal_records import (
    AuditDetails,
    NoAuditDetails,
    TeamMemberAudit,
    TeamMemberOwnerAudit,
    TeamOwnerAudit,
)
from common.platform_ids import UserId

if TYPE_CHECKING:
    from authorization._platform_application import PlatformApplication
    from teams.application import TeamAudit


class CurrentTeamTargets:
    """Keep target User checks after the Teams owner has acquired its row lock."""

    def __init__(self, application: PlatformApplication, session: AsyncSession) -> None:
        self._application = application
        self._session = session

    async def enabled(self, user_uuid: UUID) -> bool:
        target = await self._application.users.get_user(
            self._session,
            UserId(user_uuid),
            lock=True,
        )
        # Preserve the legacy target-selection contract: enabled is required;
        # current caller credential/deletion checks happen independently first.
        return target is not None and target.enabled


class TeamAuditWriter:
    """Record Teams owner facts with the existing audit/outbox transaction."""

    def __init__(self, application: PlatformApplication, session: AsyncSession) -> None:
        self._application = application
        self._session = session

    def record(self, audit: TeamAudit) -> None:
        details: AuditDetails
        if audit.team_uuid is not None and audit.new_owner_uuid is not None:
            details = TeamMemberOwnerAudit(
                team_id=audit.team_uuid, new_owner_id=audit.new_owner_uuid
            )
        elif audit.team_uuid is not None:
            details = TeamMemberAudit(team_id=audit.team_uuid)
        elif audit.new_owner_uuid is not None:
            details = TeamOwnerAudit(new_owner_id=audit.new_owner_uuid)
        else:
            details = NoAuditDetails()
        self._application._audit(
            self._session,
            actor=UserId(audit.actor_uuid),
            project=None,
            action=audit.action,
            target=audit.target,
            event=details,
        )
