"""SVC-only projection for exact common-tool continuation custody."""

from typing import Literal

from mcp.types import CallToolRequestParams, CallToolResult
from pydantic import BaseModel, ConfigDict

from hand_runtime.domain.deferred_operations import ProviderOperationBinding
from hand_runtime.provider_ipc import ProviderContext
from hand_runtime.provider_supervisor import ProviderSupervisor
from node_protocol.effect import NodeEffectPermit
from source_control.presentation.contracts import SourceTarget
from source_control.presentation.requests import SourceRequest, legacy_call


class _SourceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request: SourceRequest
    account_id: str | None = None


class _CapabilityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    target: SourceTarget


class _SourceStart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    tool: Literal["source_control"]
    arguments: _SourceArguments


class SourceProviderSupervisor(ProviderSupervisor):
    def __init__(self) -> None:
        super().__init__("svc")

    async def execute(
        self, call: CallToolRequestParams, permit: NodeEffectPermit, context: ProviderContext
    ) -> CallToolResult:
        if (
            call.name == "svc_operation_start"
            and call.arguments is not None
            and call.arguments.get("tool") == "source_control"
        ):
            selected = _SourceStart.model_validate(call.arguments)
            original = legacy_call(selected.arguments.request, selected.arguments.account_id)
            # The signed outer request was already verified by NodeDelegatedTool.
            # Retain the existing operation name so poll checks its original grant,
            # selected account, provider policy and exact process record.
            call = CallToolRequestParams(
                name=call.name,
                arguments={"tool": original.name, "arguments": original.arguments or {}},
            )
        return await super().execute(call, permit, context)

    def _provider_selection(
        self, call: CallToolRequestParams, context_digest: str
    ) -> ProviderOperationBinding:
        if call.name == "source_control_capabilities":
            capability = _CapabilityArguments.model_validate(call.arguments or {})
            return ProviderOperationBinding(None, capability.target, context_digest)
        return super()._provider_selection(call, context_digest)
