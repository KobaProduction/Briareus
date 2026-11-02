"""Control-only current authority stages; each source layout binds its own revision facts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar, Literal, NamedTuple, TypeGuard
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import (
    OwnerAuthorityUnavailable,
    OwnerCommandDTO,
    VerifiedOwnerServicePeer,
)
from common.owner_effect_authorization import (
    OwnerEffectAuthoritySnapshot,
    OwnerEffectIntent,
    SignedOwnerDecision,
    canonical_project_access_revision,
    derive_source_epoch,
)
from common.owner_proof_signing import OwnerVerifiedSourceSnapshot
from projects._persistence import ProjectRow
from projects.control.actor_contracts import TrustedControlActorSource, VerifiedControlActor
from projects.control.infrastructure.guard_bindings import (
    _ControlEffectBinding,
    _ControlProofBinding,
)
from teams._persistence import TeamMembershipRow, TeamRow


class _TeamScope(NamedTuple):
    scope_team_id: UUID | None
    team_version: int | None
    team_resource_revision: int | None
    membership_version: int | None
    team_owner_id: UUID | None
    member_active: bool


class _ControlState:
    _project_revision: ClassVar[staticmethod[[ProjectRow], int]]
    _team_revision: ClassVar[staticmethod[[TeamRow], int]]
    _membership_revision: ClassVar[staticmethod[[TeamMembershipRow], int]]


def _require_project_actor(
    peer: VerifiedOwnerServicePeer,
    actor: VerifiedControlActor,
    command: OwnerCommandDTO,
) -> None:
    if (
        peer.audience != "briareus:platform"
        or peer.expires_at <= datetime.now(UTC)
        or actor.user_id != command.caller_user_id
        or actor.credential_version != command.expected_identity_revision
        or actor.recipient_service_id != peer.service_id
        or actor.expires_at.tzinfo is None
        or actor.expires_at <= datetime.now(UTC)
    ):
        raise OwnerAuthorityUnavailable("Control actor Identity/current peer not scoped")


def _require_project_permission(
    command: OwnerCommandDTO,
    actor: VerifiedControlActor,
    owner_user: UUID | None,
    owner_team: UUID | None,
    team_scope: _TeamScope,
) -> None:
    is_project_owner = owner_user == actor.user_id
    is_team_owner = owner_team is not None and team_scope.team_owner_id == actor.user_id
    elevated = actor.role == "superuser"
    privileged = command.operation in {
        "project.delete.prepare",
        "project.delete.confirm",
        "project.withdraw_from_team",
        "project.transfer_to_team",
    }
    if command.operation == "project.transfer_to_team":
        permitted = (is_project_owner or elevated) and team_scope.member_active
    elif command.operation == "project.withdraw_from_team":
        permitted = is_team_owner or elevated
    elif command.operation in {"project.delete.prepare", "project.delete.confirm"}:
        permitted = elevated or is_project_owner or (is_team_owner and team_scope.member_active)
    elif privileged:
        permitted = False
    else:
        permitted = (
            elevated or is_project_owner or (owner_team is not None and team_scope.member_active)
        )
    if not permitted:
        raise OwnerAuthorityUnavailable("current Control membership/owner scope denied")


def _require_effect_actor(
    peer: VerifiedOwnerServicePeer,
    actor: VerifiedControlActor,
    intent: OwnerEffectIntent,
) -> None:
    now = datetime.now(UTC)
    if (
        peer.audience != "briareus:platform"
        or peer.service_id != intent.recipient_service_id
        or peer.instance_uuid != intent.recipient_instance_uuid
        or peer.expires_at <= now
        or actor.user_id != intent.actor_id
        or actor.credential_version < 1
        or actor.recipient_service_id != peer.service_id
        or actor.expires_at.tzinfo is None
        or actor.expires_at <= now
    ):
        raise OwnerAuthorityUnavailable("Control source actor/recipient mismatch")


def _require_effect_actions(
    intent: OwnerEffectIntent,
    actor: VerifiedControlActor,
    project: ProjectRow,
    team: TeamRow | None,
    membership: TeamMembershipRow | None,
) -> None:
    is_admin = actor.role == "superuser"
    is_personal = project.owner_user_id is not None and project.owner_user_id == actor.user_id
    is_member = membership is not None
    if not (is_admin or is_personal or (team is not None and is_member)):
        raise OwnerAuthorityUnavailable("actor not authorized for current Project/Team")
    if intent.action == "infrastructure.read" and not is_admin:
        raise OwnerAuthorityUnavailable("infrastructure access requires current superuser")
    if intent.action == "files.manage" and not (
        is_admin or is_personal or (team is not None and team.owner_user_id == actor.user_id)
    ):
        raise OwnerAuthorityUnavailable("Files ownership management denied")


class _ControlProjectProof(_ControlState, _ControlProofBinding[TrustedControlActorSource]):
    async def _team_scope(
        self,
        tx: AsyncSession,
        command: OwnerCommandDTO,
        actor: VerifiedControlActor,
        owner_user: UUID | None,
        owner_team: UUID | None,
    ) -> _TeamScope:
        scope_team_id: UUID | None = owner_team
        team_version: int | None = None
        team_resource_revision: int | None = None
        membership_version: int | None = None
        team_owner_id: UUID | None = None
        member_active = False
        if command.operation == "project.transfer_to_team" and owner_user is not None:
            # Recipient Team must be explicitly selected; it is NOT an
            # implicit current Project owner or inherited secret scope.
            scope_team_id = command.expected_team_id
            if scope_team_id is None:
                raise OwnerAuthorityUnavailable("Project transfer needs signed target Team")
        if scope_team_id is not None:
            team = await tx.scalar(
                select(TeamRow).where(TeamRow.id == scope_team_id).with_for_update()
            )
            if team is None:
                raise OwnerAuthorityUnavailable("authoritative Team no longer exists")
            member = await tx.scalar(
                select(TeamMembershipRow)
                .where(
                    TeamMembershipRow.team_id == scope_team_id,
                    TeamMembershipRow.user_id == actor.user_id,
                    TeamMembershipRow.active.is_(True),
                )
                .with_for_update()
            )
            member_active = member is not None
            membership_version = self._membership_revision(member) if member is not None else None
            team_version = self._team_revision(team)
            team_resource_revision = team.resource_revision
            team_owner_id = team.owner_user_id
        if (
            scope_team_id != command.expected_team_id
            or team_version != command.expected_team_revision
            or team_resource_revision != command.expected_team_resource_revision
        ):
            raise OwnerAuthorityUnavailable("Control Team or resource revisions changed")
        return _TeamScope(
            scope_team_id,
            team_version,
            team_resource_revision,
            membership_version,
            team_owner_id,
            member_active,
        )

    async def issue_project_scope(
        self,
        command: OwnerCommandDTO,
        *,
        peer_evidence: object,
        delegated_actor_evidence: object,
    ) -> SecretStr:
        try:
            peer = self.peers.verify_peer(peer_evidence)
            actor = self.actors.verify_actor(delegated_actor_evidence, service_peer=peer)
        except Exception:
            raise OwnerAuthorityUnavailable(
                "Control trusted peer/current User proof unavailable"
            ) from None
        _require_project_actor(peer, actor, command)
        async with self.db.transaction() as tx:
            project = await tx.scalar(
                select(ProjectRow).where(ProjectRow.id == command.project_id).with_for_update()
            )
            expected_state: Literal["active", "deleting"] = (
                "deleting" if command.operation == "project.delete.confirm" else "active"
            )
            if (
                project is None
                or self._project_revision(project) != command.expected_control_revision
                or project.resource_revision != command.expected_control_resource_revision
                or project.lifecycle_status != expected_state
            ):
                raise OwnerAuthorityUnavailable("Control Project revision/lifecycle changed")
            owner_user = project.owner_user_id
            owner_team = project.owner_team_id
            if (owner_user is None) == (owner_team is None):
                raise OwnerAuthorityUnavailable(
                    "Control exclusive Project ownership invariant failed"
                )
            team_scope = await self._team_scope(tx, command, actor, owner_user, owner_team)
            (
                scope_team_id,
                team_version,
                team_resource_revision,
                membership_version,
                team_owner_id,
                member_active,
            ) = team_scope
            _require_project_permission(command, actor, owner_user, owner_team, team_scope)
            snapshot = OwnerVerifiedSourceSnapshot(
                owner="platform",
                caller_user_id=actor.user_id,
                project_id=project.id,
                agent_session_uuid=command.session_uuid,
                owner_revision=self._project_revision(project),
                active=True,
                role=actor.role,
                capabilities=(command.operation,),
                control_resource_revision=project.resource_revision,
                project_lifecycle=expected_state,
                team_id=scope_team_id,
                team_revision=team_version,
                team_resource_revision=team_resource_revision,
                epoch_components=(
                    str(project.id),
                    str(self._project_revision(project)),
                    str(project.resource_revision),
                    str(owner_user or owner_team),
                    project.lifecycle_status,
                    str(scope_team_id or "none"),
                    str(team_version or "none"),
                    str(team_resource_revision or "none"),
                    str(membership_version or "none"),
                    str(member_active),
                    str(team_owner_id or "none"),
                    str(actor.user_id),
                    actor.role,
                ),
            )
            return self.signer.sign_project(command, snapshot)


class _ControlEffectDecision(_ControlState, _ControlEffectBinding[TrustedControlActorSource]):
    _project_current: ClassVar[staticmethod[[ProjectRow | None], TypeGuard[ProjectRow]]]
    _revoke_epoch: ClassVar[staticmethod[[ProjectRow, TeamRow | None], int]]

    async def decide(
        self, intent: OwnerEffectIntent, *, peer_evidence: object, delegated_actor_evidence: object
    ) -> SignedOwnerDecision:
        try:
            peer = self.peers.verify_peer(peer_evidence)
            actor = self.actors.verify_actor(delegated_actor_evidence, service_peer=peer)
        except Exception:
            raise OwnerAuthorityUnavailable(
                "current Control effect actor/peer unavailable"
            ) from None
        _require_effect_actor(peer, actor, intent)
        async with self.database.transaction() as tx:
            project = await tx.scalar(
                select(ProjectRow).where(ProjectRow.id == intent.project_id).with_for_update()
            )
            if project is None or not self._project_current(project):
                raise OwnerAuthorityUnavailable("current Control Project transfer/owner invalid")
            team: TeamRow | None = None
            membership: TeamMembershipRow | None = None
            if project.owner_team_id is not None:
                team = await tx.scalar(
                    select(TeamRow).where(TeamRow.id == project.owner_team_id).with_for_update()
                )
                if team is None:
                    raise OwnerAuthorityUnavailable("current Team ownership unavailable")
                membership = await tx.scalar(
                    select(TeamMembershipRow)
                    .where(
                        TeamMembershipRow.team_id == team.id,
                        TeamMembershipRow.user_id == actor.user_id,
                        TeamMembershipRow.active.is_(True),
                    )
                    .with_for_update()
                )
            _require_effect_actions(intent, actor, project, team, membership)
            owner_id: UUID = team.id if team is not None else project.id
            revision = canonical_project_access_revision(
                project_id=project.id,
                project_version=self._project_revision(project),
                resource_revision=project.resource_revision,
                owner_user_id=project.owner_user_id,
                owner_team_id=project.owner_team_id,
                team_version=self._team_revision(team) if team is not None else None,
                team_resource_revision=team.resource_revision if team is not None else None,
                membership_revision=self._membership_revision(membership)
                if membership is not None
                else None,
                actor_user_id=actor.user_id,
                identity_credential_revision=actor.credential_version,
                role=actor.role,
                lifecycle_status=project.lifecycle_status,
            )
            snapshot = OwnerEffectAuthoritySnapshot(
                owner="platform",
                intent=intent,
                issued_from_owner_db="briareus_platform",
                state_version=self._project_revision(project),
                revoke_epoch=self._revoke_epoch(project, team),
                authority_epoch=derive_source_epoch(
                    "platform",
                    str(project.id),
                    self._project_revision(project),
                    project.resource_revision,
                    str(owner_id),
                    self._team_revision(team) if team is not None else 0,
                    team.resource_revision if team is not None else 0,
                    self._membership_revision(membership) if membership is not None else 0,
                    actor.credential_version,
                    actor.role,
                    project.lifecycle_status,
                ),
                active=True,
                project_revision=revision,
                owner_scope="team" if team is not None else "project",
                owner_id=owner_id,
                granted_actions=(intent.action,),
                transfer_pending=False,
                source_expires_at=actor.expires_at,
            )
            return self.signer.sign(snapshot, recipient=peer)
