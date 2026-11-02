"""Adapt signed service scope to the existing read/write authority contracts."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, overload
from uuid import UUID

from fastapi import Request

from authorization.application.access_inputs import AccessCommand, ApprovalListCommand
from authorization.domain.access_commands import VerifiedAccessCommandActor
from authorization.domain.runtime_policy import RuntimeActor
from authorization.domain.session_reads import VerifiedApprovalActor
from common.platform_errors import AccessDenied


@dataclass(frozen=True, slots=True)
class VerifiedHumanRequest:
    actor: RuntimeActor
    action: str


def _write_action(
    action: str,
) -> Literal[
    "session.open", "session.request_elevation", "session.resolve_elevation", "session.revoke"
]:
    if action == "session.open":
        return "session.open"
    if action == "session.request_elevation":
        return "session.request_elevation"
    if action == "session.resolve_elevation":
        return "session.resolve_elevation"
    if action == "session.revoke":
        return "session.revoke"
    raise AccessDenied("Human operation binding mismatch")


class HumanAttestor:
    @staticmethod
    def actor(request: Request, project_uuid: UUID) -> RuntimeActor:
        context = request.scope.get("briareus.verified_human_request")
        if (
            not isinstance(context, VerifiedHumanRequest)
            or request.scope.get("briareus.service_peer") != "briareus:control-panel-api"
            or context.actor.project_uuid != project_uuid
            or context.actor.expires_at <= datetime.now(UTC)
        ):
            raise AccessDenied("Current independent Platform proof required")
        return context.actor

    @overload
    async def verify(
        self, request: Request, command: ApprovalListCommand
    ) -> VerifiedApprovalActor: ...

    @overload
    async def verify(
        self,
        request: object,
        command: AccessCommand,
        action: str,
    ) -> VerifiedAccessCommandActor: ...

    async def verify(
        self,
        request: object,
        command: ApprovalListCommand | AccessCommand,
        action: str | None = None,
    ) -> VerifiedApprovalActor | VerifiedAccessCommandActor:
        if not isinstance(request, Request):
            raise AccessDenied("Current independent Platform proof required")
        actor = self.actor(request, command.project_uuid)
        approve = "approve_agent_session" in actor.permissions
        if action is None:
            return VerifiedApprovalActor(
                actor.actor_uuid,
                actor.project_uuid,
                approve,
                "rauthy",
                "briareus:access",
                actor.expires_at,
            )
        context = request.scope.get("briareus.verified_human_request")
        if not isinstance(context, VerifiedHumanRequest) or context.action != action:
            raise AccessDenied("Human operation binding mismatch")
        if isinstance(command, ApprovalListCommand):
            raise AccessDenied("Human operation binding mismatch")
        return VerifiedAccessCommandActor(
            actor.actor_uuid,
            actor.project_uuid,
            command.operation_uuid,
            _write_action(action),
            "use_resources" in actor.permissions,
            approve,
            "rauthy",
            "briareus:access",
            actor.expires_at,
        )
