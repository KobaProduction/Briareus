"""Decode Access owner responses into the caller's named capability result."""

from pydantic import TypeAdapter

from control_panel_api._access_management_client import (
    _ApprovalOwnerItem,
    _ApprovalOwnerList,
    _SessionOwnerGet,
    _SessionOwnerItem,
    _SessionOwnerList,
)
from control_panel_api._access_management_write import _OpenReceipt
from control_panel_api.application.approval_contracts import (
    ApprovalSnapshot,
    CurrentSessionSnapshot,
    GrantSnapshot,
    OpenSessionSnapshot,
)


def approval(raw: object) -> ApprovalSnapshot:
    item = _ApprovalOwnerItem.model_validate(raw)
    return ApprovalSnapshot(
        item.id,
        item.project_uuid,
        item.agent_session_uuid,
        item.requested_by_user_uuid,
        item.status,
        item.version,
        item.requested_operations,
        tuple(effect.scope() for effect in item.requested_resources),
        item.requested_expires_at,
        item.resolved_by_user_uuid,
        item.issued_session_uuid,
        item.label,
        item.created_at,
    )


def session(item: _SessionOwnerItem) -> CurrentSessionSnapshot:
    return CurrentSessionSnapshot(
        item.session_uuid,
        item.project_uuid,
        item.created_by_user_uuid,
        item.revision,
        item.status,
        item.is_elevated,
        item.elevation_policy,
        item.hard_expires_at,
        item.operations,
        tuple(effect.scope() for effect in item.resources),
        item.allowed_actions,
        item.label,
        item.created_at,
    )


def session_list(raw: object) -> tuple[CurrentSessionSnapshot, ...]:
    return tuple(session(item) for item in _SessionOwnerList.model_validate(raw).items)


def session_detail(raw: object) -> CurrentSessionSnapshot:
    return session(_SessionOwnerGet.model_validate(raw).item)


def approval_list(raw: object) -> tuple[ApprovalSnapshot, ...]:
    return tuple(approval(item) for item in _ApprovalOwnerList.model_validate(raw).items)


def opened_session(raw: object) -> OpenSessionSnapshot:
    item = _OpenReceipt.model_validate(raw)
    return OpenSessionSnapshot(
        item.session_uuid,
        item.project_uuid,
        item.revision,
        item.status,
        item.is_elevated,
        item.elevation_policy,
        item.hard_expires_at,
        item.operations,
        tuple(effect.scope() for effect in item.resources),
    )


def revoked_session(raw: object) -> GrantSnapshot:
    return TypeAdapter(GrantSnapshot).validate_python(raw)
