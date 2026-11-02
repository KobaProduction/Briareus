"""Owner receipt identity, approval lifecycle and delegated visibility policies."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from control_panel_api.domain.approval_policy import (
    OPERATIONS,
    ApprovalLifecycle,
    aware_timestamp,
    uuid4,
)


@dataclass(frozen=True, slots=True)
class ApprovalReceiptFacts:
    approval: UUID
    project: UUID
    lifecycle: ApprovalLifecycle
    version: int
    expires_at: datetime
    operations: tuple[str, ...]

    def matches(self, *, project: UUID, actor: UUID, state: str, expected: UUID | None) -> bool:
        if (
            self.project != project
            or self.lifecycle.status != state
            or not uuid4(self.approval)
            or not uuid4(self.lifecycle.parent_session)
            or not uuid4(self.lifecycle.requester)
            or not aware_timestamp(self.expires_at)
            or (expected is not None and self.approval != expected)
        ):
            return False
        if not self._actor_state(actor, state):
            return False
        issued = self.lifecycle.issued_session
        if issued is not None and (not uuid4(issued) or issued == self.lifecycle.parent_session):
            return False
        return (
            len(set(self.operations)) == len(self.operations) and set(self.operations) <= OPERATIONS
        )

    def _actor_state(self, actor: UUID, state: str) -> bool:
        if state == "pending":
            return (
                self.version == 1
                and self.lifecycle.requester == actor
                and self.lifecycle.resolver is None
                and self.lifecycle.issued_session is None
            )
        return (
            self.version >= 2
            and self.lifecycle.requester != actor
            and self.lifecycle.resolver == actor
            and ((state == "approved") == (self.lifecycle.issued_session is not None))
        )

    def visible(
        self,
        *,
        project: UUID,
        actor: UUID,
        approver: bool,
        allowed_actions: tuple[str, ...],
        now: datetime,
    ) -> bool:
        if (
            self.project != project
            or not uuid4(self.approval)
            or not uuid4(self.lifecycle.parent_session)
            or not uuid4(self.lifecycle.requester)
            or not aware_timestamp(self.expires_at)
        ):
            return False
        if self.lifecycle.resolver is not None and not uuid4(self.lifecycle.resolver):
            return False
        if self.lifecycle.issued_session is not None and not uuid4(self.lifecycle.issued_session):
            return False
        if allowed_actions and (
            not approver
            or self.lifecycle.status != "pending"
            or self.lifecycle.requester == actor
            or self.expires_at <= now
        ):
            return False
        return approver or self.lifecycle.requester == actor
