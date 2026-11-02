"""Existing private HTTP response shapes for current owner snapshots."""

from pydantic import BaseModel

from authorization._session_payloads import ResourceGrantPayload, resource_payload
from authorization.domain.session_reads import ApprovalReadEntry, SessionReadEntry


class ApprovalEntryResponse(BaseModel):
    id: str
    project_uuid: str
    agent_session_uuid: str
    requested_by_user_uuid: str
    label: str | None
    created_at: str
    status: str
    version: int
    requested_operations: tuple[str, ...]
    requested_resources: tuple[ResourceGrantPayload, ...]
    requested_expires_at: str
    resolved_by_user_uuid: str | None
    issued_session_uuid: str | None
    allowed_actions: tuple[str, ...]


class SessionEntryResponse(BaseModel):
    session_uuid: str
    project_uuid: str
    created_by_user_uuid: str
    label: str | None
    created_at: str
    revision: int
    status: str
    is_elevated: bool
    elevation_policy: str
    hard_expires_at: str
    operations: tuple[str, ...]
    resources: tuple[ResourceGrantPayload, ...]
    allowed_actions: tuple[str, ...]


def approval_response(entry: ApprovalReadEntry) -> ApprovalEntryResponse:
    return ApprovalEntryResponse(
        id=str(entry.request_uuid),
        project_uuid=str(entry.project_uuid),
        agent_session_uuid=str(entry.session_uuid),
        requested_by_user_uuid=str(entry.requested_by_user_uuid),
        label=entry.label,
        created_at=entry.created_at.isoformat(),
        status=entry.status,
        version=entry.version,
        requested_operations=entry.operations,
        requested_resources=tuple(resource_payload(scope) for scope in entry.resources),
        requested_expires_at=entry.requested_expires_at.isoformat(),
        resolved_by_user_uuid=str(entry.resolved_by_user_uuid)
        if entry.resolved_by_user_uuid is not None
        else None,
        issued_session_uuid=str(entry.issued_session_uuid)
        if entry.issued_session_uuid is not None
        else None,
        allowed_actions=entry.allowed_actions,
    )


def session_response(entry: SessionReadEntry) -> SessionEntryResponse:
    return SessionEntryResponse(
        session_uuid=str(entry.session_uuid),
        project_uuid=str(entry.project_uuid),
        created_by_user_uuid=str(entry.created_by_user_uuid),
        label=entry.label,
        created_at=entry.created_at.isoformat(),
        revision=entry.revision,
        status=entry.status,
        is_elevated=entry.is_elevated,
        elevation_policy=entry.elevation_policy,
        hard_expires_at=entry.hard_expires_at.isoformat(),
        operations=entry.operations,
        resources=tuple(resource_payload(scope) for scope in entry.resources),
        allowed_actions=entry.allowed_actions,
    )
