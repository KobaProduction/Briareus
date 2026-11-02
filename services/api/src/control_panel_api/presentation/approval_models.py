"""Strict browser command schemas for AgentSession management."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from control_panel_api.application.approval_scopes import ScopedEffectPayload as ScopedEffectRequest


class OpenSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID
    elevation_policy: Literal["fixed", "requestable"] = "requestable"
    label: str | None = Field(default=None, max_length=128)


class RequestElevation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID
    agent_session_uuid: UUID
    operations: tuple[str, ...] = Field(min_length=1, max_length=32)
    resources: tuple[ScopedEffectRequest, ...] = Field(default=(), max_length=32)
    seconds: int = Field(strict=True, ge=1, le=300)
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)


class ResolveElevation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID
    approve: bool = Field(strict=True)
    expected_approval_version: int = Field(strict=True, ge=1, le=2**63 - 1)
    allowed_operations: tuple[str, ...] | None = Field(default=None, max_length=32)


class RevokeSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project_uuid: UUID
    expected_grant_revision: int = Field(strict=True, ge=1, le=2**63 - 1)


class ApprovalResponse(BaseModel):
    """Public approval receipt, kept separate from the outbound owner record."""

    id: str
    project_uuid: str
    agent_session_uuid: str
    requested_by_user_uuid: str
    label: str | None
    created_at: str | None
    status: Literal["pending", "approved", "rejected"]
    version: int
    requested_operations: list[str]
    requested_resources: list[ScopedEffectRequest]
    requested_expires_at: str
    resolved_by_user_uuid: str | None
    issued_session_uuid: str | None
    allowed_actions: list[str]


class SessionResponse(BaseModel):
    """Public current-session receipt, with authority-filtered actions."""

    session_uuid: str
    project_uuid: str
    created_by_user_uuid: str
    label: str | None
    created_at: str | None
    revision: int
    status: Literal["active", "revoked", "expired"]
    is_elevated: bool
    elevation_policy: Literal["fixed", "requestable"]
    hard_expires_at: str
    operations: list[str]
    resources: list[ScopedEffectRequest]
    allowed_actions: list[str]
