"""Exact private envelopes; provider-owned arguments stay in the MCP SDK adapter."""

from dataclasses import dataclass
from uuid import UUID

from mcp.types import CallToolRequestParams

from hand_runtime.analysis_call import AnalysisCommand
from reverse_hand.domain.dispatch import EngineCommand
from runtime_peer.analysis_arguments import (
    ANALYSIS_ARGUMENTS,
    AnalysisCatalogueArguments,
    AnalysisNativeArguments,
)
from runtime_peer.tool_argument_decoding import decode_tool_arguments


@dataclass(frozen=True, slots=True)
class CurrentAnalysisCall:
    request_uuid: UUID
    expires_at: int
    call: CallToolRequestParams


@dataclass(frozen=True, slots=True)
class EngineInvocation:
    command: EngineCommand
    call: CallToolRequestParams | None


def current_request(
    raw: bytes, names: frozenset[str], now: float, *, runtime_ready: bool
) -> CurrentAnalysisCall:
    command = AnalysisCommand.model_validate_json(raw)
    if command.call.name not in names or not 0 < command.expires_at - now <= 5 or not runtime_ready:
        raise ValueError("Exact current Analysis request required")
    return CurrentAnalysisCall(command.id, command.expires_at, command.call)


def engine_invocation(call: CallToolRequestParams) -> EngineInvocation:
    arguments = decode_tool_arguments(call.name, call.arguments or {}, ANALYSIS_ARGUMENTS)
    if isinstance(arguments, AnalysisNativeArguments):
        return EngineInvocation(
            EngineCommand(arguments.engine, arguments.call.name),
            arguments.call,
        )
    if isinstance(arguments, AnalysisCatalogueArguments):
        return EngineInvocation(EngineCommand(arguments.engine, None), None)
    raise ValueError("Exact actual engine tool and arguments required")
