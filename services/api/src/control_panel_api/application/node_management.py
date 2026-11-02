"""One owner command followed by fresh authority; uncertain effects never replay."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from control_panel_api.application._constructor_bindings import _ManagementBinding
from control_panel_api.application.node_contracts import NodeInput, NodeOutput
from control_panel_api.domain.operator_context import node_mutates, operator_continues
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_management import RpcFailure


@dataclass(frozen=True, slots=True)
class NodeReceipt:
    status: int
    value: NodeOutput | None = None


class NodeAuthority(Protocol):
    async def current(self, project: UUID) -> PanelContext | None: ...


class NodeOwner(Protocol):
    async def execute(self, command: NodeInput, context: PanelContext) -> NodeReceipt: ...


class NodeEvents(Protocol):
    async def committed(self, command: NodeInput, result: NodeOutput, actor: UUID) -> None: ...


class ManageNodes(_ManagementBinding[NodeAuthority, NodeOwner, NodeEvents]):
    async def execute(self, command: NodeInput) -> NodeOutput:
        original = await self._authority.current(command.project_uuid)
        if original is None:
            raise RpcFailure("CURRENT_PLATFORM_REQUIRED")
        if original.proof.role != "operator":
            raise RpcFailure("PLATFORM_OPERATOR_REQUIRED")
        if self._owner is None:
            raise RpcFailure("NODE_OWNER_UNAVAILABLE")
        deadline = min(original.session.expires_at, original.proof.expires_at)
        mutation = node_mutates(command.action, command.module.action if command.module else None)
        if deadline <= datetime.now(UTC):
            raise RpcFailure("CURRENT_PLATFORM_REQUIRED")
        receipt = await self._invoke(command, original, mutation)
        if receipt.status != 200 or receipt.value is None:
            raise self._failure(receipt.status, mutation)
        fresh = await self._authority.current(command.project_uuid)
        if fresh is None or not operator_continues(original, fresh, deadline):
            raise RpcFailure("NODE_OUTCOME_UNKNOWN", uncertain=mutation)
        if mutation:
            await self._events.committed(command, receipt.value, original.proof.user_uuid)
        return receipt.value

    async def _invoke(
        self, command: NodeInput, context: PanelContext, mutation: bool
    ) -> NodeReceipt:
        if self._owner is None:
            raise RpcFailure("NODE_OWNER_UNAVAILABLE")
        try:
            return await self._owner.execute(command, context)
        except Exception:
            raise RpcFailure("NODE_OUTCOME_UNKNOWN", uncertain=mutation) from None

    @staticmethod
    def _failure(status: int, mutation: bool) -> RpcFailure:
        code = {
            403: "NODE_PERMISSION_DENIED",
            404: "NODE_NOT_FOUND",
            409: "NODE_CONFIGURATION_CONFLICT",
            422: "NODE_COMMAND_INVALID",
        }.get(status, "NODE_OWNER_UNAVAILABLE")
        return RpcFailure(code, uncertain=mutation and status >= 500)
