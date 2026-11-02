"""Named external command receipts, shared by HTTP and runtime boundaries."""

from pydantic import BaseModel


class ResourceSelectorPayload(BaseModel):
    kind: str
    id: str


class ResourceGrantPayload(BaseModel):
    hand: str
    tool: str
    action: str
    resource: ResourceSelectorPayload


class OpenSessionResponse(BaseModel):
    session_uuid: str
    project_uuid: str
    revision: int
    status: str
    is_elevated: bool
    elevation_policy: str
    hard_expires_at: str
    operations: tuple[str, ...]
    resources: tuple[ResourceGrantPayload, ...]


class ElevationResponse(BaseModel):
    id: str
    project_uuid: str
    agent_session_uuid: str
    requested_by_user_uuid: str
    status: str
    version: int
    requested_operations: tuple[str, ...]
    requested_resources: tuple[ResourceGrantPayload, ...]
    requested_expires_at: str
    resolved_by_user_uuid: str | None
    issued_session_uuid: str | None


class RevokeSessionResponse(BaseModel):
    session_uuid: str
    project_uuid: str
    status: str
    revision: int
