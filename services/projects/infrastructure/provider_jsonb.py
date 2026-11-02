"""Native JSONB boundary for the legacy owner's concrete provider settings."""

from collections.abc import Callable

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from projects.infrastructure.provider_metadata import StoredProviderSettings


class ProviderSettingsJSONB(TypeDecorator[StoredProviderSettings]):
    impl = JSONB
    cache_ok = True

    @staticmethod
    def _require_driver(dialect: Dialect) -> None:
        if dialect.name != "postgresql" or dialect.driver != "asyncpg":
            raise ValueError("Provider JSONB requires its PostgreSQL asyncpg owner")

    def bind_processor(self, dialect: Dialect) -> Callable[[StoredProviderSettings | None], str]:
        self._require_driver(dialect)

        def encode(value: StoredProviderSettings | None) -> str:
            if not isinstance(value, StoredProviderSettings):
                raise TypeError("Typed provider settings required")
            return value.model_dump_json()

        return encode

    def result_processor(
        self, dialect: Dialect, _coltype: object
    ) -> Callable[[object], StoredProviderSettings]:
        self._require_driver(dialect)
        return StoredProviderSettings.model_validate
