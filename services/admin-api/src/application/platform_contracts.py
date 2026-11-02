"""Named legacy management command and receipt contracts."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from common.platform_errors import InvalidInput
from common.platform_ids import TeamId
from identity._domain import User


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiErrorDetail(ApiModel):
    version: Literal[1] = 1
    code: str
    message: str
    status: int


class ApiErrorEnvelope(ApiModel):
    error: ApiErrorDetail


class UserView(ApiModel):
    user_id: UUID
    username: str
    role: str
    enabled: bool
    credential_version: int

    @classmethod
    def from_user(cls, user: User) -> UserView:
        return cls(
            user_id=user.id,
            username=user.username,
            role=user.role.value,
            enabled=user.enabled,
            credential_version=user.credential_version,
        )


class TeamView(ApiModel):
    team_id: UUID
    name: str
    owner_user_id: UUID
    version: int


class TeamMembershipView(ApiModel):
    team_id: UUID
    user_id: UUID
    active: bool


class ProjectView(ApiModel):
    project_id: UUID
    name: str
    owner_user_id: UUID | None = None
    owner_team_id: UUID | None = None
    version: int


class AgentView(ApiModel):
    agent_id: UUID
    project_id: UUID
    name: str
    parent_agent_id: UUID | None
    enabled: bool
    version: int


class AgentSessionView(ApiModel):
    session_uuid: UUID
    project_id: UUID
    grants: list[str]
    is_elevated: bool
    hard_expires_at: str
    status: str
    version: int
    label: str | None = None
    elevation_policy: str


class CreateTeam(ApiModel):
    name: str = Field(min_length=1, max_length=255)


class AddMember(ApiModel):
    user_id: UUID
    expected_team_version: int = Field(ge=1)


class TransferTeamOwner(ApiModel):
    new_owner_user_id: UUID
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]


class CreateProject(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    owner_team_id: UUID | None = None


class TransferProjectOwner(ApiModel):
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]
    owner_team_id: UUID | None = None
    withdraw_to_personal: bool = False

    def target_team(self) -> TeamId | None:
        if self.withdraw_to_personal == (self.owner_team_id is not None):
            raise InvalidInput("select exactly one Project ownership transfer target")
        return TeamId(self.owner_team_id) if self.owner_team_id else None


class AdminReassignProject(ApiModel):
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]
    new_owner_user_id: UUID | None = None
    new_owner_team_id: UUID | None = None


class CreateAgent(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    parent_agent_id: UUID | None = None


class RenameAgent(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    expected_version: int = Field(ge=1)


class SetAgentEnabled(ApiModel):
    enabled: bool
    expected_version: int = Field(ge=1)
    confirmed: Literal[True]


class Register(ApiModel):
    invitation: str = Field(min_length=10, max_length=512)
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=12, max_length=4096)


class ChangePassword(ApiModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=4096)


class PasswordReset(ApiModel):
    token: str
    new_password: str = Field(min_length=12, max_length=4096)


class SuperuserRole(ApiModel):
    enabled: bool
    confirmed: Literal[True]


class DangerousConfirmation(ApiModel):
    confirmed: Literal[True]


class OpenSession(ApiModel):
    elevation_policy: str = Field("requestable", pattern="^(requestable|fixed)$")
    label: str | None = Field(default=None, min_length=1, max_length=128)


class RequestElevation(ApiModel):
    grants: list[str] = Field(min_length=1, max_length=32)
    seconds: int = Field(300, ge=1, le=300)


class ResolveElevation(ApiModel):
    expected_version: int = Field(ge=1)
    approve: bool
    allowed_grants: list[str] | None = None
    explicit_expansion_confirmation: bool = False


class PermissionView(ApiModel):
    project_id: UUID
    permissions: list[str]


class InvitationView(ApiModel):
    url: str


class ApprovalView(ApiModel):
    request_id: UUID


class ChangedView(ApiModel):
    changed: bool


class RevokedView(ApiModel):
    revoked: bool


class SessionResolutionView(ApiModel):
    session: AgentSessionView | None
