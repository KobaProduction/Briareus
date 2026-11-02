"""Verified Rauthy session and independent Platform authority facts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PanelOidcSession:
    issuer: str
    subject: str
    client_id: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PlatformTeamContext:
    team_uuid: UUID
    owner: bool
    name: str | None = None
    member: bool = True


@dataclass(frozen=True, slots=True)
class PlatformProjectContext:
    project_uuid: UUID
    owner_kind: Literal["user", "team"]
    owner_uuid: UUID
    permissions: tuple[Literal["use_resources", "approve_agent_session"], ...]
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPlatformUser:
    """Owner-verified, bounded and fresh membership snapshot."""

    issuer: str
    subject: str
    user_uuid: UUID
    enabled: bool
    role: Literal["user", "operator"]
    expires_at: datetime
    teams: tuple[PlatformTeamContext, ...]
    projects: tuple[PlatformProjectContext, ...]
    name: str | None = None
    email: str | None = None
    directory_paged: bool = False
