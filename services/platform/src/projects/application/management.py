"""Atomic operator mutations, including their replay and event evidence."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.application._authority_bindings import _FreshAuthority
from projects.domain.management import (
    ManagedProject,
    ManagedTeam,
    ManagementOutcome,
)


@dataclass(frozen=True, slots=True)
class CreateTeam:
    name: str


@dataclass(frozen=True, slots=True)
class RenameTeam:
    uuid: UUID
    expected_name: str
    name: str


@dataclass(frozen=True, slots=True)
class ChangeTeamMember:
    uuid: UUID
    user_uuid: UUID
    active: bool


@dataclass(frozen=True, slots=True)
class CreateProject:
    name: str
    team_uuid: UUID | None


@dataclass(frozen=True, slots=True)
class RenameProject:
    uuid: UUID
    expected_name: str
    name: str


Mutation = CreateTeam | RenameTeam | ChangeTeamMember | CreateProject | RenameProject


@dataclass(frozen=True, slots=True)
class ManagementCommand:
    issuer: str
    operation_uuid: UUID
    actor_uuid: UUID
    action: str
    fingerprint: str
    mutation: Mutation


class ManagementTransaction(Protocol):
    async def lock_operation(self, operation_uuid: UUID) -> None: ...
    async def require_operator(self, actor_uuid: UUID) -> None: ...
    async def previous(self, command: ManagementCommand) -> ManagementOutcome | None: ...
    async def team(self, uuid: UUID) -> ManagedTeam: ...
    async def project(self, uuid: UUID) -> ManagedProject: ...
    async def require_user(self, issuer: str, user_uuid: UUID) -> None: ...
    async def add_team(self, team: ManagedTeam) -> None: ...
    async def save_team(self, team: ManagedTeam) -> None: ...
    async def set_member(self, team_uuid: UUID, user_uuid: UUID, active: bool) -> None: ...
    async def add_project(self, project: ManagedProject) -> None: ...
    async def save_project(self, project: ManagedProject) -> None: ...
    async def record(self, command: ManagementCommand, outcome: ManagementOutcome) -> None: ...


class ManagementUnitOfWork(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[ManagementTransaction]: ...


class ManagePlatform(_FreshAuthority):
    def __init__(
        self, uow: ManagementUnitOfWork, now: Callable[[], datetime], new_uuid: Callable[[], UUID]
    ) -> None:
        self._uow = uow
        self._now = now
        self._new_uuid = new_uuid

    async def execute(self, command: ManagementCommand, deadline: datetime) -> ManagementOutcome:
        async with self._uow.transaction() as tx:
            await tx.lock_operation(command.operation_uuid)
            await tx.require_operator(command.actor_uuid)
            previous = await tx.previous(command)
            self._fresh(deadline)
            if previous is not None:
                return previous
            outcome = await self._mutate(tx, command)
            await tx.record(command, outcome)
            self._fresh(deadline)
        self._fresh(deadline, "OPERATION_OUTCOME_UNKNOWN")
        return outcome

    async def _mutate(
        self, tx: ManagementTransaction, command: ManagementCommand
    ) -> ManagementOutcome:
        change = command.mutation
        if isinstance(change, CreateTeam):
            team = ManagedTeam(self._new_uuid(), change.name, command.actor_uuid, 0)
            await tx.add_team(team)
            await tx.set_member(team.uuid, command.actor_uuid, True)
            return team.outcome()
        if isinstance(change, (RenameTeam, ChangeTeamMember)):
            return await self._change_team(tx, command, change)
        if isinstance(change, CreateProject):
            if change.team_uuid is not None:
                await tx.team(change.team_uuid)
            project = ManagedProject(
                self._new_uuid(),
                change.name,
                command.actor_uuid if change.team_uuid is None else None,
                change.team_uuid,
            )
            await tx.add_project(project)
            return project.outcome()
        project = await tx.project(change.uuid)
        project.rename(change.expected_name, change.name)
        await tx.save_project(project)
        return project.outcome()

    async def _change_team(
        self,
        tx: ManagementTransaction,
        command: ManagementCommand,
        change: RenameTeam | ChangeTeamMember,
    ) -> ManagementOutcome:
        team = await tx.team(change.uuid)
        if isinstance(change, RenameTeam):
            team.rename(change.expected_name, change.name)
        else:
            await tx.require_user(command.issuer, change.user_uuid)
            team.change_member(change.user_uuid, change.active)
            await tx.set_member(team.uuid, change.user_uuid, change.active)
        await tx.save_team(team)
        return team.outcome()
