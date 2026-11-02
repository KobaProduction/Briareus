"""Closed SQL event schemas for existing owner command and lease protocols."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OwnerMutationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_uuid: UUID
    project_id: UUID
    event: str = Field(min_length=1, max_length=128)


class TeamChangedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    team_id: UUID
    actor_user_id: UUID
    subject_id: UUID
    operation_uuid: UUID


class LeaseRedemptionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_uuid: UUID
    lease_id: UUID


class IntegrationCredentialRedeemed(LeaseRedemptionEvent):
    project_id: UUID
    service_id: UUID


class VariableCredentialRedeemed(LeaseRedemptionEvent):
    resource_id: UUID


type CatalogEvent = OwnerMutationEvent | IntegrationCredentialRedeemed | VariableCredentialRedeemed
type TeamOwnerEvent = OwnerMutationEvent | TeamChangedEvent
