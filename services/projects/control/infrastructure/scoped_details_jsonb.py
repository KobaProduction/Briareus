"""One owner's versioned, concrete public scope metadata in its existing JSONB column."""

import json
from collections.abc import Callable

from pydantic import BaseModel, Field, StrictInt, TypeAdapter
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from projects.domain.scope_events import ScopeEventDetails
from service_runtime._scoped_record_result import _ScopedRecordResult

_DETAILS = TypeAdapter(ScopeEventDetails)


class _StorageVersion(BaseModel):
    schema_version: StrictInt = Field(ge=1, le=1)


def _decode(value: object) -> ScopeEventDetails:
    if not isinstance(value, dict):
        raise ValueError("Scoped event storage document required")
    if "schema_version" in value:
        _StorageVersion.model_validate(value)
        if set(value) != {"schema_version", "record"}:
            raise ValueError("Scoped event storage envelope invalid")
        value = value["record"]
        if not isinstance(value, dict):
            raise ValueError("Scoped event storage record required")
    return _DETAILS.validate_json(json.dumps(value, allow_nan=False), strict=True)


class ScopedDetailsJSONB(_ScopedRecordResult[ScopeEventDetails], TypeDecorator[ScopeEventDetails]):
    impl = JSONB
    cache_ok = True

    _decode_record = staticmethod(_decode)

    def bind_processor(self, dialect: Dialect) -> Callable[[ScopeEventDetails | None], str]:
        self._require_driver(dialect)

        def encode(value: ScopeEventDetails | None) -> str:
            if not isinstance(value, ScopeEventDetails):
                raise TypeError("Typed public scope-event metadata required")
            record = _DETAILS.dump_json(value, exclude_none=True, warnings="error").decode()
            return '{"schema_version":1,"record":' + record + "}"

        return encode
