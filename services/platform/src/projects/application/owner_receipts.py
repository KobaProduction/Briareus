"""Named owner command receipts before durable ledger serialization."""

from __future__ import annotations

from pydantic import BaseModel


class ControlConfirmProjectDelete(BaseModel):
    project_id: str
    lifecycle_status: str
    state: str
    resource_revision: int
    native_artifacts_removed: bool
    physical_cleanup_verified: bool


class ControlCreateAgent(BaseModel):
    agent_id: str
    project_id: str
    resource_revision: int


class ControlMovePersonalToTeam(BaseModel):
    project_id: str
    owner_team_id: str
    state: str
    resource_revision: int


class ControlPrepareProjectDelete(BaseModel):
    project_id: str
    lifecycle_status: str
    fenced_control_revision: int
    resource_revision: int
    reconciliation_required: bool


class ControlWithdrawTeamProject(BaseModel):
    project_id: str
    owner_user_id: str
    state: str
    resource_revision: int
