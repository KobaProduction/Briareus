"""Concrete retained-session boundary models; Identity remains the credential authority."""

from typing import Self
from uuid import UUID

from domain.web_session import WebUser
from pydantic import BaseModel, ConfigDict

from common.access_contracts import AccessRequests, AccessSessions, SurfaceControls, UserControls


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str


class WebUserView(BaseModel):
    id: UUID
    username: str
    role: str
    enabled: bool

    @classmethod
    def from_record(cls, user: WebUser) -> Self:
        return cls(id=user.id, username=user.username, role=user.role, enabled=user.enabled)

    def domain(self) -> WebUser:
        return WebUser(self.id, self.username, self.role, self.enabled)


class WebAccessSessions(AccessSessions):
    user: WebUserView


class WebAccessRequests(AccessRequests):
    user: WebUserView


class WebSurfaceControls(SurfaceControls):
    user: WebUserView


class WebUserControls(UserControls):
    user: WebUserView


class WebSessionRevoked(BaseModel):
    session_id: UUID
