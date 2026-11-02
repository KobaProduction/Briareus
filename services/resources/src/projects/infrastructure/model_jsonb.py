"""Resources-only typed JSONB storage for the owner's asyncpg database.

The database representation has its own explicit schema version. Consumers see
the concrete validated model, never the storage envelope or an arbitrary map.
The bind processor emits the same JSON string expected by asyncpg's JSONB codec.
"""

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator


class StorageHeader(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: StrictInt = Field(ge=1, le=1)


class ModelJSONB[ModelT: BaseModel](TypeDecorator[ModelT]):
    impl = JSONB
    cache_ok = True

    def __init__(
        self, model: type[ModelT], *, allow_none: bool = False, invalid_as_none: bool = False
    ) -> None:
        super().__init__()
        self.model = model
        self.allow_none = allow_none
        # Catalogue inputs already deny publication when their stored contract
        # is invalid. Preserve that explicit unapproved state instead of making
        # a damaged build definition usable or preventing operator repair.
        self.invalid_as_none = invalid_as_none

    def bind_processor(self, dialect: Dialect) -> Callable[[ModelT | None], str | None]:
        self._require_driver(dialect)

        return self._encode

    def _encode(self, value: ModelT | None) -> str | None:
        if value is None:
            if not self.allow_none:
                raise TypeError(f"Non-null {self.model.__name__} storage model required")
            return None
        if not isinstance(value, self.model):
            raise TypeError(f"{self.model.__name__} storage model required")
        return '{"schema_version":1,"record":' + value.model_dump_json(exclude_unset=True) + "}"

    def result_processor(
        self, dialect: Dialect, _coltype: object
    ) -> Callable[[object], ModelT | None]:
        self._require_driver(dialect)

        return self._decode

    def _decode(self, value: object) -> ModelT | None:
        if value is None:
            if self.allow_none or self.invalid_as_none:
                return None
            raise ValueError(f"Non-null {self.model.__name__} storage document required")
        try:
            if not isinstance(value, dict) or set(value) != {"schema_version", "record"}:
                raise ValueError("Versioned Resources JSONB document required")
            StorageHeader.model_validate(value)
            if value["record"] is None and self.allow_none:
                return None
            return self.model.model_validate(value["record"])
        except ValueError:
            if self.invalid_as_none:
                return None
            raise

    @staticmethod
    def _require_driver(dialect: Dialect) -> None:
        if dialect.name != "postgresql" or dialect.driver != "asyncpg":
            raise ValueError("Resources typed JSONB requires its PostgreSQL asyncpg owner")
