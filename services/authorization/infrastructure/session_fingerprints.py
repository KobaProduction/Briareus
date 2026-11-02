"""Existing source-session replay identities; these are not new request/authority DTOs."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from authorization.application.session_receipts import ResourceGrantPayload


class SessionFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    uuid: UUID
    payload_sha256: str


class OpenSessionFingerprint(SessionFingerprint):
    policy: str
    label: str | None


class ElevationFingerprint(SessionFingerprint):
    grants: tuple[str, ...]
    seconds: int
    resources: tuple[ResourceGrantPayload, ...]


class ResolutionFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    uuid: UUID
    approval_id: UUID
    approve: bool
    allowed_grants: tuple[str, ...] | None
    expected_approval_version: int
    confirmed: bool
