"""Bounded correlated private Serena messages, distinct from execution authority."""

from uuid import UUID

from mcp.types import CallToolRequestParams, CallToolResult

from hand_runtime.provider_results import ProviderReply
from node_protocol.effect import NodeEffectPermit

from .private_messages import PrivateRequest, ReadyCatalogue


def decode_catalogue(raw: bytes) -> ReadyCatalogue:
    if not raw or len(raw) > 1000000:
        raise ValueError("Bounded actual Serena metadata required")
    catalogue = ReadyCatalogue.model_validate_json(raw)
    catalogue.validate_catalogue()
    return catalogue


def encode_command(
    call: CallToolRequestParams,
    permit: NodeEffectPermit,
    *,
    background: bool,
) -> bytes:
    command = PrivateRequest(
        id=permit.request_uuid,
        call=call,
        expires_at=permit.expires_at,
        background=background,
    )
    payload = command.wire_json(exclude_none=True).encode() + b"\n"
    if len(payload) > 32768:
        raise ValueError("Bounded exact Serena command required")
    return payload


def decode_reply(raw: bytes, operation: UUID) -> CallToolResult:
    if not raw or len(raw) > 1000000:
        raise ValueError("Serena result expired or unavailable")
    reply = ProviderReply.model_validate_json(raw)
    if reply.id != operation:
        raise ValueError("Correlated original Serena MCP result required")
    return reply.result
