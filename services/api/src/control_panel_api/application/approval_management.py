"""Approval and session use cases over an independently authorized owner port."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from control_panel_api.domain.approval_policy import (
    OPERATIONS,
    EffectScope,
    uuid4,
    valid_effects,
    valid_label,
    valid_operations,
)

from .approval_contracts import (
    ApprovalManagementPort,
    ApprovalSnapshot,
    CurrentSessionSnapshot,
    GrantSnapshot,
    OpenSessionSnapshot,
)
from .approval_execution import ApprovalFailure, ApprovalFailureCode, execute_owner
from .approval_receipts import SessionReader, valid_approval, valid_opened_session


@dataclass(frozen=True, slots=True)
class ApprovalActor:
    user: UUID
    project: UUID
    approver: bool
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ElevationCommand:
    session: UUID
    operations: tuple[str, ...]
    resources: tuple[EffectScope, ...]
    seconds: int
    expected_revision: int
    operation: UUID


@dataclass(frozen=True, slots=True)
class ResolutionCommand:
    approval: UUID
    expected_version: int
    approve: bool
    allowed_operations: tuple[str, ...] | None
    operation: UUID


@dataclass(frozen=True, slots=True)
class ApprovalManagement:
    owner: ApprovalManagementPort
    actor: ApprovalActor

    def valid_approval(self, item: object) -> bool:
        if not isinstance(item, ApprovalSnapshot) or not valid_approval(
            item, project=self.actor.project
        ):
            return False
        return valid_effects(
            item.requested_resources,
            operations=item.requested_operations,
            unique=True,
        )

    def valid_session(self, item: object) -> bool:
        reader = SessionReader(
            self.actor.user,
            self.actor.project,
            self.actor.approver,
            datetime.now(UTC),
        )
        if not isinstance(item, CurrentSessionSnapshot) or not reader.accepts(item):
            return False
        return valid_effects(item.resources, operations=item.operations, unique=False)

    def approval_list(self, result: object) -> tuple[ApprovalSnapshot, ...] | ApprovalFailure:
        if not isinstance(result, tuple) or len(result) > 50:
            return ApprovalFailure(ApprovalFailureCode.INVALID_RECEIPT)
        items: list[ApprovalSnapshot] = []
        seen: set[UUID] = set()
        for item in result:
            if not isinstance(item, ApprovalSnapshot) or not self.valid_approval(item):
                return ApprovalFailure(ApprovalFailureCode.INVALID_RECEIPT)
            if item.approval_uuid in seen:
                return ApprovalFailure(ApprovalFailureCode.INVALID_RECEIPT)
            if not self.actor.approver and item.requested_by_user_uuid != self.actor.user:
                return ApprovalFailure(ApprovalFailureCode.INVALID_RECEIPT)
            seen.add(item.approval_uuid)
            items.append(item)
        return tuple(items)

    async def list_approvals(self) -> tuple[ApprovalSnapshot, ...] | ApprovalFailure:
        result = await execute_owner(
            self.owner.list_approvals(actor=self.actor.user, project=self.actor.project, limit=50),
            expires_at=self.actor.expires_at,
        )
        if isinstance(result, ApprovalFailure):
            return result
        return self.approval_list(result)

    def session_list(self, result: object) -> tuple[CurrentSessionSnapshot, ...] | ApprovalFailure:
        if not isinstance(result, tuple) or len(result) > 50:
            return ApprovalFailure(ApprovalFailureCode.INVALID_SESSION_RECEIPT)
        items: list[CurrentSessionSnapshot] = []
        seen: set[UUID] = set()
        for item in result:
            if not isinstance(item, CurrentSessionSnapshot) or not self.valid_session(item):
                return ApprovalFailure(ApprovalFailureCode.INVALID_SESSION_RECEIPT)
            if item.session_uuid in seen:
                return ApprovalFailure(ApprovalFailureCode.INVALID_SESSION_RECEIPT)
            seen.add(item.session_uuid)
            items.append(item)
        return tuple(items)

    async def list_sessions(self) -> tuple[CurrentSessionSnapshot, ...] | ApprovalFailure:
        result = await execute_owner(
            self.owner.list_sessions(actor=self.actor.user, project=self.actor.project, limit=50),
            expires_at=self.actor.expires_at,
        )
        if isinstance(result, ApprovalFailure):
            return result
        return self.session_list(result)

    async def get_session(self, session: UUID) -> CurrentSessionSnapshot | ApprovalFailure:
        if not uuid4(session):
            return ApprovalFailure(ApprovalFailureCode.INVALID_SESSION)
        result = await execute_owner(
            self.owner.get_session(
                actor=self.actor.user, project=self.actor.project, session=session
            ),
            expires_at=self.actor.expires_at,
        )
        if isinstance(result, ApprovalFailure):
            return result
        if not self.valid_session(result) or result.session_uuid != session:
            return ApprovalFailure(ApprovalFailureCode.INVALID_SESSION_RECEIPT)
        return result

    async def open_session(
        self,
        *,
        elevation_policy: Literal["fixed", "requestable"],
        label: str | None,
        operation: UUID,
    ) -> OpenSessionSnapshot | ApprovalFailure:
        if not valid_label(label) or (label is not None and label != label.strip()):
            return ApprovalFailure(ApprovalFailureCode.INVALID_LABEL)
        result = await execute_owner(
            self.owner.open_normal(
                actor=self.actor.user,
                project=self.actor.project,
                elevation_policy=elevation_policy,
                label=label,
                operation=operation,
            ),
            expires_at=self.actor.expires_at,
        )
        if isinstance(result, ApprovalFailure):
            return result
        if not valid_opened_session(
            result,
            project=self.actor.project,
            elevation_policy=elevation_policy,
            now=datetime.now(UTC),
        ):
            return ApprovalFailure(ApprovalFailureCode.INVALID_RECEIPT)
        return result

    def valid_request(self, command: ElevationCommand) -> bool:
        if not uuid4(command.session) or not valid_operations(command.operations):
            return False
        effects = command.resources
        if not valid_effects(effects, operations=command.operations, unique=True):
            return False
        return {effect.action for effect in effects} == set(command.operations)

    def valid_request_receipt(self, result: object, command: ElevationCommand) -> bool:
        if not isinstance(result, ApprovalSnapshot) or not self.valid_approval(result):
            return False
        return all(
            (
                result.requested_by_user_uuid == self.actor.user,
                result.agent_session_uuid == command.session,
                result.status == "pending",
                result.version == 1,
                result.approval_uuid == command.operation,
                set(result.requested_operations) == set(command.operations),
                self.same_scopes(result.requested_resources, command.resources),
            )
        )

    def same_scopes(
        self,
        first: tuple[EffectScope, ...],
        second: tuple[EffectScope, ...],
    ) -> bool:
        return set(first) == set(second)

    async def request_elevation(
        self, command: ElevationCommand
    ) -> ApprovalSnapshot | ApprovalFailure:
        if not self.valid_request(command):
            return ApprovalFailure(ApprovalFailureCode.INVALID_SCOPE)
        result = await execute_owner(
            self.owner.request_elevation(
                actor=self.actor.user,
                project=self.actor.project,
                session=command.session,
                operations=command.operations,
                resources=command.resources,
                seconds=command.seconds,
                expected_grant_revision=command.expected_revision,
                operation=command.operation,
            ),
            expires_at=self.actor.expires_at,
        )
        if isinstance(result, ApprovalFailure):
            return result
        if not self.valid_request_receipt(result, command):
            return ApprovalFailure(ApprovalFailureCode.INVALID_RECEIPT)
        return result

    def valid_resolution(self, command: ResolutionCommand) -> bool:
        if not uuid4(command.approval):
            return False
        operations = command.allowed_operations
        if operations is None:
            return True
        return len(set(operations)) == len(operations) and set(operations).issubset(OPERATIONS)

    def valid_resolution_receipt(self, result: object, command: ResolutionCommand) -> bool:
        if not isinstance(result, ApprovalSnapshot) or not self.valid_approval(result):
            return False
        return all(
            (
                result.approval_uuid == command.approval,
                result.requested_by_user_uuid != self.actor.user,
                result.resolved_by_user_uuid == self.actor.user,
                result.version == command.expected_version + 1,
                result.status == ("approved" if command.approve else "rejected"),
            )
        )

    async def resolve_elevation(
        self, command: ResolutionCommand
    ) -> ApprovalSnapshot | ApprovalFailure:
        if not self.valid_resolution(command):
            return ApprovalFailure(ApprovalFailureCode.INVALID_SCOPE)
        result = await execute_owner(
            self.owner.resolve_elevation(
                actor=self.actor.user,
                project=self.actor.project,
                approval=command.approval,
                expected_version=command.expected_version,
                approve=command.approve,
                allowed_operations=command.allowed_operations,
                operation=command.operation,
            ),
            expires_at=self.actor.expires_at,
        )
        if isinstance(result, ApprovalFailure):
            return result
        if not self.valid_resolution_receipt(result, command):
            return ApprovalFailure(ApprovalFailureCode.INVALID_RECEIPT)
        return result

    async def revoke_session(
        self,
        *,
        session: UUID,
        expected_revision: int,
        operation: UUID,
    ) -> GrantSnapshot | ApprovalFailure:
        if not uuid4(session):
            return ApprovalFailure(ApprovalFailureCode.INVALID_SESSION)
        result = await execute_owner(
            self.owner.revoke_session(
                actor=self.actor.user,
                project=self.actor.project,
                session=session,
                expected_revision=expected_revision,
                operation=operation,
            ),
            expires_at=self.actor.expires_at,
        )
        if isinstance(result, ApprovalFailure):
            return result
        if not valid_revocation(
            result, project=self.actor.project, session=session, expected_revision=expected_revision
        ):
            return ApprovalFailure(ApprovalFailureCode.INVALID_RECEIPT)
        return result


def valid_revocation(
    result: object,
    *,
    project: UUID,
    session: UUID,
    expected_revision: int,
) -> bool:
    if not isinstance(result, GrantSnapshot):
        return False
    return (
        result.project_uuid == project
        and result.session_uuid == session
        and result.status == "revoked"
        and type(result.revision) is int
        and result.revision > expected_revision
    )
