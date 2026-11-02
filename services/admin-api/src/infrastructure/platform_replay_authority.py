"""Current, locked legacy authority checks before decrypting command receipts."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._project_access import CallerPrincipal
from common.platform_errors import AccessDenied, AuthenticationRequired, InvalidInput
from common.platform_ids import PlatformProjectId, TeamId
from identity._domain import UserRole
from identity._service import IdentityService


@dataclass(frozen=True)
class PlatformReplayAuthority:
    application: PlatformApplication
    identity: IdentityService
    caller: CallerPrincipal | None
    operation: str
    project_scope: str
    owner_team_id: UUID | None

    async def reauthorize(self, tx: AsyncSession) -> None:
        if self.caller is None:
            if self.operation not in {"identity.register", "identity.password.reset"}:
                raise AuthenticationRequired("verified caller required")
            return
        user = await self.application.current_user(tx, self.caller, lock=True)
        admin = user.role is UserRole.SUPERUSER
        action, _, suffix = self.operation.partition(":")
        if action.startswith("team."):
            await self._team(tx, action, suffix, admin)
        elif action.startswith("project."):
            await self._project(tx, action, admin)
        elif action.startswith(("agent.", "session.")):
            await self.application.project_allowed(
                tx, self.caller, PlatformProjectId(UUID(self.project_scope))
            )
        else:
            await self._identity(tx, action, suffix, admin)

    async def _team(self, tx: AsyncSession, action: str, suffix: str, admin: bool) -> None:
        if action == "team.create":
            return
        if action not in {"team.member.add", "team.member.remove", "team.transfer_owner"}:
            raise InvalidInput("unrecognized idempotent operation")
        if self.caller is None:
            raise AuthenticationRequired("verified caller required")
        team = await self.application.teams.get(tx, TeamId(UUID(suffix)), lock=True)
        if team is None or (not admin and team.owner_user_id != self.caller.user_id):
            raise AccessDenied("Team owner permission required")

    async def _project(self, tx: AsyncSession, action: str, admin: bool) -> None:
        if action == "project.create":
            await self._project_creation(tx, admin)
        elif action == "project.admin_reassign":
            if not admin:
                raise AccessDenied("superuser permission required")
        elif action == "project.transfer_owner":
            await self._project_transfer(tx, admin)
        else:
            raise InvalidInput("unrecognized idempotent operation")

    async def _project_creation(self, tx: AsyncSession, admin: bool) -> None:
        if self.owner_team_id is None:
            return
        if self.caller is None:
            raise AuthenticationRequired("verified caller required")
        team_id = TeamId(self.owner_team_id)
        team = await self.application.teams.get(tx, team_id, lock=True)
        if team is None or (
            not admin
            and not await self.application.teams.active_member(tx, team_id, self.caller.user_id)
        ):
            raise AccessDenied("Team Project creation permission required")

    async def _project_transfer(self, tx: AsyncSession, admin: bool) -> None:
        if self.caller is None:
            raise AuthenticationRequired("verified caller required")
        row = await self.application.projects.get(
            tx, PlatformProjectId(UUID(self.project_scope)), lock=True
        )
        if row is None:
            raise AccessDenied("Project unavailable")
        if admin:
            return
        if row.owner_user_id is not None:
            if row.owner_user_id != self.caller.user_id:
                raise AccessDenied("personal Project owner required")
            return
        if row.owner_team_id is None:
            raise AccessDenied("Project ownership unavailable")
        team = await self.application.teams.get(tx, TeamId(row.owner_team_id), lock=True)
        if team is None or team.owner_user_id != self.caller.user_id:
            raise AccessDenied("Team owner required")

    async def _identity(self, tx: AsyncSession, action: str, suffix: str, admin: bool) -> None:
        if action in {
            "identity.suspend",
            "identity.restore",
            "identity.superuser",
            "identity.password_reset.issue",
            "identity.delete",
        }:
            if not admin:
                raise AccessDenied("superuser permission required")
            return
        if action == "identity.invitation.revoke":
            if self.caller is None:
                raise AuthenticationRequired("verified caller required")
            invitation = await self.identity.repository.get_invitation(tx, UUID(suffix), lock=True)
            if invitation is None or (
                invitation.created_by_user_id != self.caller.user_id and not admin
            ):
                raise AccessDenied("invitation permission required")
            return
        if action not in {"identity.invite", "identity.password.change"}:
            raise InvalidInput("unrecognized idempotent operation")
