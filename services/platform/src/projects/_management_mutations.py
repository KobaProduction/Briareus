"""Decode existing Panel mutation fields and wire the Platform use case."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from common.platform_db import PlatformDatabase
from projects.application.management import (
    ChangeTeamMember,
    CreateProject,
    CreateTeam,
    ManagementCommand,
    ManagePlatform,
    Mutation,
    RenameProject,
    RenameTeam,
)
from projects.domain.management import ManagementOutcome, identifier, name
from projects.infrastructure.management import SqlManagementUnitOfWork
from projects.presentation.management_inputs import (
    ChangeMemberQuery,
    CreateProjectQuery,
    CreateTeamQuery,
    MutationQuery,
    RenameTeamQuery,
)


def mutation(query: MutationQuery) -> Mutation:
    if isinstance(query, CreateTeamQuery):
        return CreateTeam(name(query.data.name))
    if isinstance(query, RenameTeamQuery):
        return RenameTeam(
            identifier(query.data.id), query.data.expected_name, name(query.data.name)
        )
    if isinstance(query, ChangeMemberQuery):
        return ChangeTeamMember(
            identifier(query.data.id),
            identifier(query.data.user_id),
            query.action == "team.member.add",
        )
    if isinstance(query, CreateProjectQuery):
        team_uuid = None if query.data.team_id is None else identifier(query.data.team_id)
        return CreateProject(name(query.data.name), team_uuid)
    return RenameProject(identifier(query.data.id), query.data.expected_name, name(query.data.name))


async def manage(
    database: PlatformDatabase,
    query: MutationQuery,
    actor_uuid: UUID,
    digest: str,
    deadline: datetime,
) -> ManagementOutcome:
    use_case = ManagePlatform(SqlManagementUnitOfWork(database), lambda: datetime.now(UTC), uuid4)
    command = ManagementCommand(
        query.issuer,
        query.operation_uuid,
        actor_uuid,
        query.action,
        digest,
        mutation(query),
    )
    return await use_case.execute(command, deadline)
