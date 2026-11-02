"""Two concrete producer formats for Resources' existing integration JSONB column."""

from collections.abc import Callable

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from projects.infrastructure.connection_metadata import StoredConnectionSettings
from projects.infrastructure.provider_metadata import StoredProviderSettings

type IntegrationSettings = StoredProviderSettings | StoredConnectionSettings


def decode_integration_settings(value: object) -> IntegrationSettings:
    if not isinstance(value, dict):
        raise ValueError("Stored integration settings required")
    kind = value.get("settings_kind")
    if kind is None:
        # Existing connection-form producers wrote these fields; catalogue
        # producers wrote only the public provider metadata fields.
        kind = (
            "connection"
            if set(value)
            & {"name", "provider", "auth_type", "git_policy", "external_id", "ca_cert_pem"}
            else "catalog"
        )
    if kind == "connection":
        return StoredConnectionSettings.model_validate(value)
    if kind == "catalog":
        return StoredProviderSettings.model_validate(value)
    raise ValueError("Unknown integration settings producer format")


def connection_metadata(settings: IntegrationSettings) -> StoredConnectionSettings:
    if isinstance(settings, StoredConnectionSettings):
        return settings
    # Concrete projection at the storage adapter; no map crosses the port.
    return StoredConnectionSettings.model_validate_json(settings.model_dump_json())


class IntegrationSettingsJSONB(TypeDecorator[IntegrationSettings]):
    impl = JSONB
    cache_ok = True

    @staticmethod
    def _require_driver(dialect: Dialect) -> None:
        if dialect.name != "postgresql" or dialect.driver != "asyncpg":
            raise ValueError("Integration JSONB requires its PostgreSQL asyncpg owner")

    def bind_processor(self, dialect: Dialect) -> Callable[[IntegrationSettings | None], str]:
        self._require_driver(dialect)

        def encode(value: IntegrationSettings | None) -> str:
            if isinstance(value, StoredConnectionSettings):
                kind, document = "connection", value.model_dump_json(exclude_none=True)
            elif isinstance(value, StoredProviderSettings):
                kind, document = "catalog", value.model_dump_json()
            else:
                raise TypeError("Concrete integration settings required")
            # Keep the existing flat v1 schema; old readers ignore the new
            # producer discriminator. Each concrete model declares its version.
            return '{"settings_kind":"' + kind + '",' + document[1:]

        return encode

    def result_processor(
        self, dialect: Dialect, _coltype: object
    ) -> Callable[[object], IntegrationSettings]:
        self._require_driver(dialect)
        return decode_integration_settings
