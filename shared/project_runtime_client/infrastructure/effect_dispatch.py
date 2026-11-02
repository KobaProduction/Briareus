"""Bounded invocation of the owner transport port, with uncertain ACK semantics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from project_runtime_client.domain.effect_receipt import OwnerEffectUnavailable

if TYPE_CHECKING:
    from project_runtime_client.a11_owner_wire import A11OwnerCommandDTO
    from project_runtime_client.authorization import ProjectInvocation
    from project_runtime_client.owner_authorization import VerifiedOwnerRecipient
    from project_runtime_client.owner_effects import (
        OwnerEffectBackendPort,
        OwnerEffectCommand,
        OwnerEffectReply,
    )
    from project_runtime_client.owner_wire import A11OwnerWire


@dataclass(frozen=True, slots=True)
class EffectDispatch[T: BaseModel, PayloadT: BaseModel]:
    command: OwnerEffectCommand
    source_command: A11OwnerCommandDTO
    wire: A11OwnerWire
    payload: PayloadT
    expected: type[T]
    peer: VerifiedOwnerRecipient


async def dispatch_effect[T: BaseModel, PayloadT: BaseModel](
    backend: OwnerEffectBackendPort | None,
    invocation: ProjectInvocation,
    *,
    dispatch: EffectDispatch[T, PayloadT],
    timeout_seconds: float,
) -> OwnerEffectReply[T]:
    if backend is None:
        raise OwnerEffectUnavailable("OWNER_A11_SIGNED_DURABLE_PORTS_REQUIRED")
    try:
        async with asyncio.timeout(timeout_seconds):
            return await backend.effect(
                invocation,
                command=dispatch.command,
                a11_command=dispatch.source_command,
                business_payload=dispatch.wire.business_payload,
                payload=dispatch.payload,
                expected_type=dispatch.expected,
                recipient=dispatch.peer,
            )
    except Exception as exc:
        raise OwnerEffectUnavailable("OWNER_EFFECT_OUTCOME_UNKNOWN", unknown=True) from exc
