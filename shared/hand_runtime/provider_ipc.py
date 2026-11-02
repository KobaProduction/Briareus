"""Typed, bounded provider IPC with exact original context and result fields."""

from __future__ import annotations

import hashlib
import json
from typing import Self
from uuid import UUID

from mcp.types import CallToolRequestParams, CallToolResult
from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    StrictBool,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from node_protocol.effect import NodeEffectPermit
from node_protocol.provider_context import InvocationContext

from .deferred_call_domain import ProviderOperationBinding
from .private_call import PrivateToolCall
from .provider_results import ProviderReply


class PreparationReady(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    ready: StrictBool

    @field_validator("ready")
    @classmethod
    def confirmed(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Metadata preparation is incomplete")
        return value

    @classmethod
    def decode(cls, raw: bytes, *, failure: str) -> Self:
        source = raw.decode(json.detect_encoding(raw), "surrogatepass")
        try:
            return cls.model_validate_json(source)
        except ValidationError:
            raise ValueError(failure) from None


class ProviderContext(InvocationContext):
    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_unset=True),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(encoded.encode()).hexdigest()


class ProviderCommand(PrivateToolCall):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: UUID
    context: ProviderContext
    expires_at: int | float
    background: bool = False

    @field_validator("context", mode="before")
    @classmethod
    def context_from_wire(
        cls, value: ProviderContext | JsonValue, info: ValidationInfo[None]
    ) -> ProviderContext:
        if isinstance(value, ProviderContext):
            return value
        # PrivateToolCall reconstructs the flat SDK envelope in its wrap validator.
        # Preserve JSON tuple/UUID decoding for the nested owner context only.
        if info.mode == "json":
            return ProviderContext.model_validate_json(json.dumps(value, allow_nan=False))
        return ProviderContext.model_validate(value)


def require_ready(raw: bytes) -> None:
    if len(raw) > 64:
        raise ValueError("Provider metadata preparation failed")
    PreparationReady.decode(raw, failure="Provider metadata preparation failed")


def encode_command(
    call: CallToolRequestParams,
    permit: NodeEffectPermit,
    context: ProviderContext,
    *,
    background: bool,
) -> bytes:
    command = ProviderCommand(
        id=permit.request_uuid,
        call=call,
        context=context,
        expires_at=permit.expires_at,
        background=background,
    )
    payload = command.wire_json(exclude_unset=True).encode() + b"\n"
    if len(payload) > 131072:
        raise ValueError("Bounded provider request required")
    return payload


def decode_reply(raw: bytes, request_uuid: UUID) -> CallToolResult:
    if not raw or len(raw) > 1000000:
        raise ValueError("Current provider result unavailable")
    reply = ProviderReply.model_validate_json(raw)
    if reply.id != request_uuid:
        raise ValueError("Correlated provider outcome required")
    return reply.result


class _ProviderSelection(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    account_id: StrictStr | None = None
    provider: StrictStr | None = None


def provider_selection(call: CallToolRequestParams, digest: str) -> ProviderOperationBinding:
    selection = _ProviderSelection.model_validate(call.arguments or {})
    return ProviderOperationBinding(selection.account_id, selection.provider, digest)
