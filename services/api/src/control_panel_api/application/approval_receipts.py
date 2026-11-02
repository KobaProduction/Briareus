"""Validate independently owned receipts before exposing them to a browser."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from control_panel_api.domain.approval_policy import (
    ApprovalLifecycle,
    SessionState,
    aware_timestamp,
    bounded_resources,
    optional_timestamp,
    positive_revision,
    uuid4,
    valid_label,
    valid_operations,
)

from .approval_contracts import ApprovalSnapshot, CurrentSessionSnapshot, OpenSessionSnapshot


def approval_lifecycle(item: ApprovalSnapshot) -> ApprovalLifecycle:
    return ApprovalLifecycle(
        item.status,
        item.requested_by_user_uuid,
        item.agent_session_uuid,
        item.resolved_by_user_uuid,
        item.issued_session_uuid,
    )


def valid_approval(item: object, *, project: UUID) -> bool:
    if not isinstance(item, ApprovalSnapshot):
        return False
    return all(
        (
            uuid4(item.approval_uuid),
            item.project_uuid == project,
            uuid4(item.agent_session_uuid),
            uuid4(item.requested_by_user_uuid),
            valid_label(item.label),
            optional_timestamp(item.created_at),
            positive_revision(item.version),
            aware_timestamp(item.requested_expires_at),
            valid_operations(item.requested_operations),
            bounded_resources(item.requested_resources),
            approval_lifecycle(item).valid(),
        )
    )


@dataclass(frozen=True, slots=True)
class SessionReader:
    actor: UUID
    project: UUID
    approver: bool
    now: datetime

    def accepts(self, item: object) -> bool:
        if not isinstance(item, CurrentSessionSnapshot):
            return False
        return all(
            (
                uuid4(item.session_uuid),
                item.project_uuid == self.project,
                uuid4(item.created_by_user_uuid),
                self.approver or item.created_by_user_uuid == self.actor,
                positive_revision(item.revision),
                valid_label(item.label),
                optional_timestamp(item.created_at),
                valid_operations(item.operations),
                bounded_resources(item.resources),
                isinstance(item.allowed_actions, tuple),
                SessionState(
                    item.status,
                    item.is_elevated,
                    item.elevation_policy,
                    item.hard_expires_at,
                    item.allowed_actions,
                ).valid(now=self.now, approver=self.approver),
            )
        )


def valid_opened_session(
    item: object,
    *,
    project: UUID,
    elevation_policy: str,
    now: datetime,
) -> bool:
    if not isinstance(item, OpenSessionSnapshot):
        return False
    if not aware_timestamp(item.hard_expires_at):
        return False
    return all(
        (
            uuid4(item.session_uuid),
            item.project_uuid == project,
            item.status == "active",
            item.is_elevated is False,
            item.elevation_policy == elevation_policy,
            type(item.revision) is int and item.revision == 1,
            now < item.hard_expires_at <= now + timedelta(hours=24),
            item.operations == ("files.read", "project.metadata.read"),
            not item.resources,
        )
    )
