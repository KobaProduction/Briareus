"""Web protocol adaptation for the shared owned deferred-operation lifecycle."""

import time
from typing import Protocol

from mcp.types import CallToolRequestParams, CallToolResult, TextContent, Tool

from hand_runtime.application.deferred_operations import DeferredOperations
from hand_runtime.deferred_calls import original_call
from hand_runtime.domain.deferred_operations import (
    DeferredRecord,
    ExecutionOutcome,
    OperationAuthority,
)
from hand_runtime.presentation.deferred_operations import (
    CancelOperationRequest,
    PollOperationRequest,
    operation_handle_wire,
)
from hand_runtime.process_lease_domain import LeaseIdentity
from node_protocol.effect import EffectPermit

from .infrastructure.browser_ipc import BrowserReply, WebOperationView


class WebOperations(Protocol):
    deferred: DeferredOperations[CallToolResult]
    metadata: list[Tool]
    status_warm: bool

    async def exchange(
        self,
        call: CallToolRequestParams,
        permit: EffectPermit,
        *,
        startup: bool = False,
        background: bool = False,
    ) -> BrowserReply: ...

    @staticmethod
    def operation_reply(
        record: DeferredRecord[CallToolResult],
        permit: EffectPermit,
    ) -> BrowserReply:
        view = WebOperationView(
            operation_id=operation_handle_wire(record.operation_id),
            tool=record.tool,
            state=record.state,
        )
        if record.result is not None:
            view = view.model_copy(update={"result": record.result})
        return BrowserReply(
            id=permit.request_uuid,
            result=CallToolResult(
                content=[TextContent(type="text", text="Web operation: " + record.state)],
                structured_content=view.model_dump(mode="json", by_alias=True, exclude_unset=True),
                is_error=False,
            ),
        )

    async def operation_control(
        self,
        call: CallToolRequestParams,
        permit: EffectPermit,
        identity: LeaseIdentity,
    ) -> BrowserReply:
        polling = call.name == "web_operation_poll"
        command = (
            PollOperationRequest.model_validate(call.arguments or {})
            if polling
            else CancelOperationRequest.model_validate(call.arguments or {})
        )
        record = await self.deferred.control(
            command.handle(),
            polling=polling,
            tool=command.tool if isinstance(command, PollOperationRequest) else None,
            authority=OperationAuthority(identity, permit.expires_at, permit.request_uuid),
        )
        return self.operation_reply(record, permit)

    async def operation_start(
        self,
        call: CallToolRequestParams,
        permit: EffectPermit,
        identity: LeaseIdentity,
    ) -> BrowserReply:
        original = original_call(
            call,
            {item.name for item in self.metadata},
            "web_operation_",
            compact=True,
        )
        if not self.status_warm or permit.expires_at <= time.time():
            raise ValueError("Bounded original Web tool and prepared browser required")

        async def dispatch() -> ExecutionOutcome[CallToolResult]:
            reply = await self.exchange(original, permit, background=True)
            if reply.result is None:
                raise ValueError("Browser operation failed")
            return ExecutionOutcome(reply.result, reply.result.is_error)

        record = await self.deferred.start(
            original.name,
            OperationAuthority(identity, permit.expires_at, permit.request_uuid),
            dispatch,
        )
        return self.operation_reply(record, permit)
