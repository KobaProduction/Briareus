"""MCP adapter for bounded process-local operations; callers own the dispatch lock."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Collection
from uuid import uuid4

from fastmcp import FastMCP
from mcp.types import CallToolRequestParams, CallToolResult, TextContent

from node_protocol.effect import NodeEffectPermit

from .application.deferred_operations import DeferredOperations, OperationLease
from .domain.deferred_operations import (
    DeferredRecord,
    ExecutionOutcome,
    OperationAuthority,
    OperationHandle,
    ProviderOperationBinding,
)
from .presentation.deferred_operations import (
    CancelOperationRequest,
    OperationStatusView,
    PollOperationRequest,
    operation_handle_wire,
    register_deferred_start,
)
from .process_lease_domain import LeaseIdentity
from .runtime_policy import runtime_policy

type ExecuteOriginal = Callable[
    [CallToolRequestParams, NodeEffectPermit], Awaitable[CallToolResult]
]


def original_call(
    request: CallToolRequestParams, tools: Collection[str], prefix: str, *, compact: bool = False
) -> CallToolRequestParams:
    values = request.arguments or {}
    tool, arguments = values.get("tool"), values.get("arguments")
    if (
        set(values) != {"tool", "arguments"}
        or not isinstance(tool, str)
        or not isinstance(arguments, dict)
        or tool not in tools
        or tool.startswith(prefix)
        or len(
            json.dumps(
                values,
                allow_nan=False,
                sort_keys=compact,
                separators=(",", ":") if compact else None,
            ).encode()
        )
        > 32000
    ):
        raise ValueError("Bounded original tool and prepared runtime required")
    return CallToolRequestParams(name=tool, arguments=arguments)


class OperationView(OperationStatusView):
    result: CallToolResult | None = None


def _authority(permit: NodeEffectPermit, identity: LeaseIdentity) -> OperationAuthority:
    return OperationAuthority(identity, permit.expires_at, permit.request_uuid)


class DeferredCalls:
    def __init__(
        self,
        module: str,
        *,
        lock: asyncio.Lock,
        lease: OperationLease,
        ready: Callable[[], bool],
        tools: Callable[[], Collection[str]],
        execute: ExecuteOriginal,
        stop: Callable[[], Awaitable[None]],
        recover: Callable[[], None],
    ) -> None:
        self.prefix = module + "_operation_"
        self._tools, self._execute = tools, execute
        self._operations = DeferredOperations[CallToolResult](
            boot=uuid4(),
            lock=lock,
            lease=lease,
            ready=ready,
            stop=stop,
            recover=recover,
            clock=time.time,
            timeout=lambda: runtime_policy().execution_timeout_seconds,
        )

    def lookup(self, operation_id: OperationHandle) -> DeferredRecord[CallToolResult] | None:
        return self._operations.book.lookup(operation_id)

    def running(self) -> bool:
        return self._operations.book.running()

    def interrupt(self) -> None:
        self._operations.interrupt()

    def bind_provider(
        self, operation_id: OperationHandle, binding: ProviderOperationBinding
    ) -> None:
        record = self.lookup(operation_id)
        if record is None:
            raise ValueError("Exact owned operation required")
        record.provider_binding = binding

    def result(self, record: DeferredRecord[CallToolResult]) -> CallToolResult:
        view = OperationView(
            operation_id=operation_handle_wire(record.operation_id),
            tool=record.tool,
            state=record.state,
            result=record.result,
        )
        return CallToolResult(
            content=[TextContent(type="text", text="Operation: " + record.state)],
            structured_content=view.model_dump(mode="json", exclude_none=True, by_alias=True),
            is_error=False,
        )

    async def control(
        self,
        name: str,
        command: PollOperationRequest | CancelOperationRequest,
        permit: NodeEffectPermit,
        identity: LeaseIdentity,
    ) -> CallToolResult:
        polling = name == self.prefix + "poll"
        if name not in {self.prefix + "poll", self.prefix + "cancel"}:
            raise ValueError("Known operation control required")
        if polling != isinstance(command, PollOperationRequest):
            raise ValueError("Exact operation control required")
        record = await self._operations.control(
            command.handle(),
            polling=polling,
            tool=command.tool if isinstance(command, PollOperationRequest) else None,
            authority=_authority(permit, identity),
        )
        return self.result(record)

    async def start(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
        identity: LeaseIdentity,
    ) -> CallToolResult:
        command = original_call(call, self._tools(), self.prefix)

        async def execute_original() -> ExecutionOutcome[CallToolResult]:
            result = await self._execute(command, permit)
            return ExecutionOutcome(result, result.is_error)

        record = await self._operations.start(
            command.name, _authority(permit, identity), execute_original
        )
        return self.result(record)


def register_deferred_tools[LifespanT](mcp: FastMCP[LifespanT], module: str) -> None:
    prefix = module + "_operation_"

    register_deferred_start(
        mcp,
        name=prefix + "start",
        description="""Start one long original tool with current authority and retain its handle.

Use initial_instructions to prepare this identity first. Poll every two
seconds with the returned operation_id and exact original tool. Native
processes pause within five seconds without fresh rights. Start/poll
also require current rights to the original tool. Never blindly retry
a start whose reply was lost. Only one operation runs per placement.
Worker replacement invalidates handles and never replays old effects.""",
        reason="Metadata only; trusted parent executes",
    )

    @mcp.tool(name=prefix + "poll", output_schema=None)
    async def poll(operation_id: str, tool: str) -> CallToolResult:
        """Resume an owned operation with current original-tool + start + poll rights.

        If the start reply was lost, operation_id="request:<original start request UUID>"
        resolves the same operation without replay.

        This may continue an effect, not merely read a result. Another actor,
        AgentSession, revision or tool cannot resume or retrieve the operation.
        """
        del operation_id, tool
        raise RuntimeError("Metadata only; trusted parent executes")

    @mcp.tool(name=prefix + "cancel", output_schema=None)
    async def cancel(operation_id: str) -> CallToolResult:
        """Stop an owned operation without resuming it or undoing prior effects.

        Native processes stop; project files remain. Cancellation is not rollback.
        """
        del operation_id
        raise RuntimeError("Metadata only; trusted parent executes")
