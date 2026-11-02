"""Concrete poll/cancel protocol and the existing canonical operation handle framing."""

from uuid import UUID

from fastmcp import FastMCP
from fastmcp.tools import Tool
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, StrictStr
from pydantic.json_schema import JsonSchemaValue

from hand_runtime.domain.deferred_operations import (
    OperationHandle,
    OperationState,
    ProviderOperationBinding,
)


def register_deferred_start[State](
    mcp: FastMCP[State], *, name: str, description: str, reason: str
) -> None:
    # This describes an original MCP call; the trusted supervisor binds and
    # authorizes its native CallToolRequestParams before any execution.
    parameters: JsonSchemaValue = {
        "type": "object",
        "properties": {
            "tool": {"type": "string"},
            "arguments": {"type": "object", "additionalProperties": {}},
        },
        "required": ["tool", "arguments"],
    }
    metadata = Tool(name=name, description=description, parameters=parameters, output_schema=None)

    async def unavailable(**arguments: object) -> CallToolResult:
        del arguments
        raise RuntimeError(reason)

    tool = Tool.from_tool(metadata, transform_fn=unavailable, output_schema=None)
    mcp.add_tool(tool.model_copy(update={"parameters": parameters}))


class OperationStatusView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    operation_id: str
    tool: str
    state: OperationState


def parse_operation_handle(value: str) -> OperationHandle:
    boot, separator, request = value.partition(":")
    if not separator:
        raise ValueError("Exact owned operation required")
    request_uuid = UUID(request)
    boot_uuid = None if boot == "request" else UUID(boot)
    if str(request_uuid) != request or (boot_uuid is not None and str(boot_uuid) != boot):
        raise ValueError("Canonical operation handle required")
    return OperationHandle(boot_uuid, request_uuid)


def operation_handle_wire(handle: OperationHandle) -> str:
    boot = "request" if handle.boot is None else str(handle.boot)
    return boot + ":" + str(handle.request_uuid)


class CancelOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_id: StrictStr

    def handle(self) -> OperationHandle:
        return parse_operation_handle(self.operation_id)


class PollOperationRequest(CancelOperationRequest):
    tool: StrictStr


class ProviderOperationControl(PollOperationRequest):
    account_id: StrictStr | None = None
    provider: StrictStr | None = None

    def binding(self) -> ProviderOperationBinding:
        return ProviderOperationBinding(self.account_id, self.provider, "")

    def command(self, *, polling: bool) -> PollOperationRequest | CancelOperationRequest:
        if polling:
            return PollOperationRequest(operation_id=self.operation_id, tool=self.tool)
        return CancelOperationRequest(operation_id=self.operation_id)
