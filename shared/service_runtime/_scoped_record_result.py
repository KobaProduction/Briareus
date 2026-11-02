"""Driver admission and typed result dispatch without owner record codecs."""

from abc import abstractmethod
from collections.abc import Callable
from typing import Protocol


class _DriverDialect(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def driver(self) -> str: ...


class _ScopedRecordResult[RecordT]:
    @staticmethod
    @abstractmethod
    def _decode_record(value: object, /) -> RecordT: ...

    @staticmethod
    def _require_driver(dialect: _DriverDialect) -> None:
        if dialect.name != "postgresql" or dialect.driver != "asyncpg":
            raise ValueError("Scoped JSONB requires its PostgreSQL asyncpg owner")

    def result_processor(
        self, dialect: _DriverDialect, _coltype: object
    ) -> Callable[[object], RecordT]:
        self._require_driver(dialect)
        return self._decode_record
