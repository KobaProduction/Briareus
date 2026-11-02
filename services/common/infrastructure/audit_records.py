"""Concrete SQL audit facts shared by owner command and resource access adapters."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OperationAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_uuid: UUID


class UserRoleAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Literal["user", "superuser"]


class TeamOperationAudit(OperationAudit):
    team_id: UUID


class ResourceAccessAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_id: UUID
    service_id: UUID


type CatalogAudit = OperationAudit | ResourceAccessAudit
