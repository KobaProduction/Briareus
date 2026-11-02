"""Locked reusable resource authority for legacy encrypted replay."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._project_access import CallerPrincipal
from common.platform_errors import AccessDenied, InvalidInput
from projects._resource_domain import OwnerScope, ResourceOwner
from projects._resource_persistence import IntegrationRow, VariableRow
from projects._resource_service import ResourceService, owner_of


@dataclass(frozen=True)
class ResourceReplayAuthority:
    resources: ResourceService
    caller: CallerPrincipal
    owner_scope: str
    operation: str

    async def reauthorize(self, tx: AsyncSession) -> None:
        # Every retry is re-authorized at the same locked owner scope
        # before a stored idempotency response is decrypted/replayed.
        owner = await self._owner(tx)
        await self.resources._check_owner(tx, self.caller, owner, lock=True)

    async def _owner(self, tx: AsyncSession) -> ResourceOwner:
        selector, _, qualified_id = self.owner_scope.partition(":")
        try:
            owner_id = UUID(qualified_id)
        except ValueError as exc:
            raise InvalidInput("invalid resource owner selector") from exc
        if selector == "team":
            return ResourceOwner(OwnerScope.TEAM, owner_id)
        if selector == "project":
            return ResourceOwner(OwnerScope.PROJECT, owner_id)
        if selector != "resource":
            raise InvalidInput("unknown resource owner selector")
        return await self._persisted_owner(tx, owner_id)

    async def _persisted_owner(self, tx: AsyncSession, owner_id: UUID) -> ResourceOwner:
        record: IntegrationRow | VariableRow | None
        if self.operation.startswith("integration."):
            record = await tx.scalar(select(IntegrationRow).where(IntegrationRow.id == owner_id))
        elif self.operation.startswith("variable."):
            record = await tx.scalar(select(VariableRow).where(VariableRow.id == owner_id))
        else:
            raise InvalidInput("unknown scoped resource operation")
        if record is None:
            raise AccessDenied("resource unavailable")
        return owner_of(record)
