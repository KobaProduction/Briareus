"""The existing private native IPC, expressed with SDK calls and bounded headers."""

from dataclasses import dataclass
from uuid import UUID

from mcp.types import CallToolRequestParams, Tool
from pydantic import BaseModel, ConfigDict, StrictBool

from hand_runtime.analysis_call import AnalysisCommand
from node_protocol.effect import NodeEffectPermit


class ChildReady(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ready: StrictBool
    tools: tuple[Tool, ...] | None = None


@dataclass(frozen=True, slots=True)
class ChildInvocation:
    id: UUID
    expires_at: int
    call: CallToolRequestParams


def encode_call(call: CallToolRequestParams, permit: NodeEffectPermit) -> bytes:
    return AnalysisCommand(id=permit.request_uuid, call=call, expires_at=permit.expires_at).encode()


def decode_call(raw: bytes, allowed: frozenset[str], now: float) -> ChildInvocation:
    command = AnalysisCommand.model_validate_json(raw)
    if command.call.name not in allowed or not 0 < command.expires_at - now <= 5:
        raise ValueError("Exact current analysis request required")
    return ChildInvocation(command.id, command.expires_at, command.call)
