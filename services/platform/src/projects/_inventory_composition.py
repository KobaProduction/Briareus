"""Compose the read-only Platform inventory with the existing provider reader."""

from datetime import UTC, datetime
from typing import Protocol

from common.platform_db import PlatformDatabase
from projects._oidc_membership_projection import CurrentRauthyPlatformMembership
from projects.application.inventory import InventoryQuery, ProfileReader, ReadInventory
from projects.domain.inventory import Inventory
from projects.domain.management import identifier
from projects.infrastructure.inventory import SqlInventoryReader
from projects.presentation.management_inputs import InventoryQuery as InventoryCommand
from projects.presentation.management_inputs import TeamReadQuery


class InventoryService(ProfileReader, Protocol):
    db: PlatformDatabase


async def read_inventory(
    service: InventoryService,
    query: InventoryCommand,
    actor: CurrentRauthyPlatformMembership,
    deadline: datetime,
) -> Inventory:
    use_case = ReadInventory(SqlInventoryReader(service.db), service, lambda: datetime.now(UTC))
    return await use_case.execute(
        InventoryQuery(query.issuer, actor.user_id, actor.role == "operator"), deadline
    )


async def read_team(
    service: InventoryService,
    query: TeamReadQuery,
    actor: CurrentRauthyPlatformMembership,
    deadline: datetime,
) -> Inventory:
    team_uuid = identifier(query.data.id)
    member = any(team.team_id == team_uuid and team.member for team in actor.teams)
    use_case = ReadInventory(SqlInventoryReader(service.db), service, lambda: datetime.now(UTC))
    return await use_case.execute(
        InventoryQuery(
            query.issuer,
            actor.user_id,
            actor.role == "operator",
            team_uuid,
            member,
        ),
        deadline,
    )
