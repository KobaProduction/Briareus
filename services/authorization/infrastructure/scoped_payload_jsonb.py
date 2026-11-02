"""Versioned Access-owned scope projection; only the database driver sees JSON."""

from collections.abc import Callable

from pydantic import BaseModel, Field, StrictInt, TypeAdapter
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from authorization.domain.scoped_event_policy import PublicScopePayload
from authorization.infrastructure.scoped_event_codec import decode_public_scope_payload
from service_runtime._scoped_record_result import _ScopedRecordResult

_PAYLOAD = TypeAdapter(PublicScopePayload)


class _StorageVersion(BaseModel):
    schema_version: StrictInt = Field(ge=1, le=1)


def _decode(value: object) -> PublicScopePayload:
    if not isinstance(value, dict):
        raise ValueError("Scoped event storage document required")
    if "schema_version" in value:
        _StorageVersion.model_validate(value)
        if set(value) != {"schema_version", "record"}:
            raise ValueError("Scoped event storage envelope invalid")
        value = value["record"]
        if not isinstance(value, dict):
            raise ValueError("Scoped event storage record required")
    return decode_public_scope_payload(value)


class ScopedPayloadJSONB(
    _ScopedRecordResult[PublicScopePayload], TypeDecorator[PublicScopePayload]
):
    impl = JSONB
    cache_ok = True

    _decode_record = staticmethod(_decode)

    def bind_processor(self, dialect: Dialect) -> Callable[[PublicScopePayload | None], str]:
        self._require_driver(dialect)

        def encode(value: PublicScopePayload | None) -> str:
            if not isinstance(value, PublicScopePayload):
                raise TypeError("Typed scoped event metadata required")
            record = _PAYLOAD.dump_json(value, exclude_none=True, warnings="error").decode()
            return '{"schema_version":1,"record":' + record + "}"

        return encode
