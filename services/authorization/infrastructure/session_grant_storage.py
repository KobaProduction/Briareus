"""Access-owned versioned JSONB codec; malformed stored facts never grant authority."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from authorization._session_payloads import resource_payload
from authorization.application.session_receipts import ResourceGrantPayload
from authorization.domain.sessions import SessionResourceGrant
from authorization.infrastructure.resource_scopes import decode_resource_grants


@dataclass(frozen=True, slots=True)
class StoredSessionPermissions:
    # None marks a malformed field, distinct from a valid empty collection.
    # Keep both facts so an obsolete approval can still be rejected.
    operations: tuple[str, ...] | None = ()
    resources: tuple[SessionResourceGrant, ...] | None = ()


class _PermissionDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[1] = 1
    operations: tuple[Annotated[str, Field(max_length=128)], ...] = Field(max_length=32)
    resources: tuple[ResourceGrantPayload, ...] = Field(max_length=32)


def _operations(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or len(value) > 32:
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or len(item) > 128:
            return None
        result.append(item)
    return tuple(result)


def _resources(value: object) -> tuple[SessionResourceGrant, ...] | None:
    try:
        return decode_resource_grants(value)
    except ValueError:
        return None


def decode_session_permissions(value: object) -> StoredSessionPermissions:
    if not isinstance(value, dict):
        return StoredSessionPermissions(None, None)
    version = value.get("schema_version", 0)
    if type(version) is not int or version not in {0, 1}:
        return StoredSessionPermissions(None, None)
    if version == 1 and set(value) != {"schema_version", "operations", "resources"}:
        return StoredSessionPermissions(None, None)
    return StoredSessionPermissions(
        _operations(value.get("operations")), _resources(value.get("resources", []))
    )


class SessionPermissionsJSONB(TypeDecorator[StoredSessionPermissions]):
    """Reuse the owner JSONB processor pattern; the driver alone receives JSON text."""

    impl = JSONB
    cache_ok = True

    @staticmethod
    def _require_driver(dialect: Dialect) -> None:
        if dialect.name != "postgresql" or dialect.driver != "asyncpg":
            raise ValueError("Access typed JSONB requires its PostgreSQL asyncpg owner")

    def bind_processor(self, dialect: Dialect) -> Callable[[StoredSessionPermissions | None], str]:
        self._require_driver(dialect)

        def encode(value: StoredSessionPermissions | None) -> str:
            if not isinstance(value, StoredSessionPermissions):
                raise TypeError("Typed session permissions required")
            if value.operations is None or value.resources is None:
                raise ValueError("Malformed session permissions cannot be written")
            return _PermissionDocument(
                operations=value.operations,
                resources=tuple(resource_payload(scope) for scope in value.resources),
            ).model_dump_json()

        return encode

    def result_processor(
        self, dialect: Dialect, _coltype: object
    ) -> Callable[[object], StoredSessionPermissions]:
        self._require_driver(dialect)
        return decode_session_permissions
