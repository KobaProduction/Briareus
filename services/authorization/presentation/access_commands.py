"""Existing idempotent management response payloads at the JSON boundary."""

from authorization._session_payloads import resource_payload
from authorization.application.session_receipts import ElevationResponse as ElevationResponse
from authorization.application.session_receipts import OpenSessionResponse as OpenSessionResponse
from authorization.application.session_receipts import (
    RevokeSessionResponse as RevokeSessionResponse,
)
from authorization.domain.sessions import ElevationRequest, SessionState


def open_response(state: SessionState) -> OpenSessionResponse:
    return OpenSessionResponse(
        session_uuid=str(state.session_uuid),
        project_uuid=str(state.project_uuid),
        revision=state.version,
        status=state.status,
        is_elevated=state.is_elevated,
        elevation_policy=state.elevation_policy,
        hard_expires_at=state.hard_expires_at.isoformat(),
        operations=state.grants,
        resources=tuple(resource_payload(scope) for scope in state.resources),
    )


def elevation_response(request: ElevationRequest) -> ElevationResponse:
    return ElevationResponse(
        id=str(request.request_uuid),
        project_uuid=str(request.project_uuid),
        agent_session_uuid=str(request.session_uuid),
        requested_by_user_uuid=str(request.requested_by_user_uuid),
        status=request.status,
        version=request.version,
        requested_operations=request.grants,
        requested_resources=tuple(resource_payload(scope) for scope in request.resources),
        requested_expires_at=request.requested_expires_at.isoformat(),
        resolved_by_user_uuid=str(request.resolved_by_user_uuid)
        if request.resolved_by_user_uuid is not None
        else None,
        issued_session_uuid=str(request.issued_session_uuid)
        if request.issued_session_uuid is not None
        else None,
    )


def revoke_response(state: SessionState) -> RevokeSessionResponse:
    return RevokeSessionResponse(
        session_uuid=str(state.session_uuid),
        project_uuid=str(state.project_uuid),
        status=state.status,
        revision=state.version,
    )
