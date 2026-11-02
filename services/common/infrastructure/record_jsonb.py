"""PostgreSQL asyncpg codec for finite, validated SQL storage record schemas.

Only the driver boundary accepts unstructured input. Each owner supplies a
finite record schema. The existing flat document representation stays intact.
"""

from collections.abc import Callable

from pydantic import BaseModel, TypeAdapter
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.sql.operators import OperatorType
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator


class RecordJSONB[RecordT: BaseModel](TypeDecorator[RecordT]):
    impl = JSONB()
    cache_ok = True

    def __init__(
        self,
        adapter: TypeAdapter[RecordT],
        *,
        exclude_none: bool = True,
        exclude_unset: bool = False,
    ) -> None:
        super().__init__()
        self.adapter = adapter
        self.exclude_none = exclude_none
        self.exclude_unset = exclude_unset

    def coerce_compared_value(self, op: OperatorType | None, value: object) -> TypeEngine[object]:
        # JSON path operands are native index strings, not complete records.
        return self.impl.coerce_compared_value(op, value)

    def bind_processor(self, dialect: Dialect) -> Callable[[RecordT | None], str]:
        self._require_driver(dialect)

        def encode(value: RecordT | None) -> str:
            record = self.adapter.validate_python(value)
            return record.model_dump_json(
                exclude_none=self.exclude_none, exclude_unset=self.exclude_unset, warnings="error"
            )

        return encode

    def result_processor(self, dialect: Dialect, _coltype: object) -> Callable[[object], RecordT]:
        self._require_driver(dialect)

        return self.adapter.validate_python

    @staticmethod
    def _require_driver(dialect: Dialect) -> None:
        if dialect.name != "postgresql" or dialect.driver != "asyncpg":
            raise ValueError("Typed SQL records require PostgreSQL asyncpg")
