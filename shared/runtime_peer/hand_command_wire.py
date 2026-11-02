"""Existing operation and authority selectors shared by human Hand command envelopes."""

from pydantic import UUID4, BaseModel, ConfigDict, Field


class ProjectCommandHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID4
    operation_uuid: UUID4
    tool: str = Field(min_length=1, max_length=128)


class HandCommandHeader(ProjectCommandHeader):
    agent_session_uuid: UUID4
    expected_grant_revision: int = Field(strict=True, ge=1)
