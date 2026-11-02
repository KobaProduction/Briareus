"""Inspect and retry keep the original operation and idempotency identity."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .effect_receipt import OwnerEffectUnavailable
from .identifiers import valid_uuid


@dataclass(frozen=True, slots=True)
class EmbeddedEffectIdentity:
    operations: tuple[UUID, ...]
    idempotency_key: str | None


@dataclass(frozen=True, slots=True)
class OriginalEffectIdentity:
    operation_uuid: UUID

    @classmethod
    def bind(cls, request_uuid: UUID, original_uuid: UUID | None) -> OriginalEffectIdentity:
        operation_uuid = original_uuid or request_uuid
        if operation_uuid != request_uuid or not valid_uuid(operation_uuid, version=4):
            raise OwnerEffectUnavailable("OWNER_ORIGINAL_UUID_MISMATCH")
        return cls(operation_uuid)

    def require_payload(self, embedded: EmbeddedEffectIdentity) -> None:
        if any(value != self.operation_uuid for value in embedded.operations):
            raise OwnerEffectUnavailable("OWNER_EMBEDDED_ORIGINAL_UUID_MISMATCH")
        if embedded.idempotency_key is not None and embedded.idempotency_key != str(
            self.operation_uuid
        ):
            raise OwnerEffectUnavailable("OWNER_EMBEDDED_IDEMPOTENCY_KEY_MISMATCH")
