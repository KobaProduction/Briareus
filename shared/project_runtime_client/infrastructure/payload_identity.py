"""Validate optional legacy model fields before constructing operation facts."""

from uuid import UUID

from pydantic import BaseModel

from project_runtime_client.domain.effect_identity import EmbeddedEffectIdentity
from project_runtime_client.domain.effect_receipt import OwnerEffectUnavailable


def payload_effect_identity(payload: BaseModel) -> EmbeddedEffectIdentity:
    operations: list[UUID] = []
    for field in ("operation_uuid", "original_operation_uuid"):
        value = getattr(payload, field, None)
        if value is None:
            continue
        if not isinstance(value, UUID):
            raise OwnerEffectUnavailable("OWNER_EMBEDDED_ORIGINAL_UUID_MISMATCH")
        operations.append(value)
    key = getattr(payload, "idempotency_key", None)
    if key is not None and not isinstance(key, str):
        raise OwnerEffectUnavailable("OWNER_EMBEDDED_IDEMPOTENCY_KEY_MISMATCH")
    return EmbeddedEffectIdentity(tuple(operations), key)
