import logging
from collections.abc import Callable, Iterator
from typing import cast

import valkey
from briareus_cache.settings import ValkeySettings
from briareus_environment_models import ProcessSettings
from briareus_service_catalog import ServiceDefinition
from pydantic import Field, ValidationError

logger = logging.getLogger(__name__)


class RegistrySettings(ProcessSettings):
    environment: str = Field(validation_alias="DEPLOYMENT_ENVIRONMENT", pattern=r"^[a-zA-Z0-9_-]+$")


class ServiceRegistry:
    """Node-scoped inventory persists; each running instance has a short lease."""

    def __init__(self, settings: ValkeySettings | None = None) -> None:
        cache = settings or ValkeySettings()
        self.environment = RegistrySettings().environment
        self.prefix = f"{cache.namespace}:services:{self.environment}:"
        self.client = valkey.Valkey.from_url(
            cache.url,
            username=cache.username,
            password=cache.password,
            decode_responses=True,
            socket_connect_timeout=cache.socket_connect_timeout_seconds,
            socket_timeout=cache.socket_timeout_seconds,
        )

    def announce(self, service: ServiceDefinition, instance: str) -> None:
        try:
            self.client.set(self.prefix + "inventory:" + service.id, service.model_dump_json())
            self.client.set(self.prefix + f"lease:{service.id}:{instance}", "1", ex=20)
        except valkey.exceptions.ValkeyError:
            logger.warning("Service registration unavailable service=%s", service.id)

    def withdraw(self, service: ServiceDefinition, instance: str) -> None:
        try:
            self.client.delete(self.prefix + f"lease:{service.id}:{instance}")
        except valkey.exceptions.ValkeyError:
            logger.warning("Service lease cleanup unavailable service=%s", service.id)

    def inventory(self) -> tuple[ServiceDefinition, ...]:
        result = []
        try:
            keys = cast(
                Iterator[str], self.client.scan_iter(match=self.prefix + "inventory:*", count=100)
            )
            for index, key in enumerate(keys):
                if index >= 1000:
                    break
                raw = cast(str | None, self.client.get(key))
                if raw is not None:
                    try:
                        result.append(ServiceDefinition.model_validate_json(raw))
                    except ValidationError:
                        logger.warning("Invalid service registry entry ignored")
        except valkey.exceptions.ValkeyError:
            logger.warning("Service inventory temporarily unavailable")
        return tuple(result)

    def close(self) -> None:
        close = cast(Callable[[], None], self.client.close)
        close()

    def active_services(self) -> frozenset[str]:
        """Leases bind candidates to this environment before any network probing."""
        prefix = self.prefix + "lease:"
        result: set[str] = set()
        try:
            keys = cast(Iterator[str], self.client.scan_iter(match=prefix + "*", count=100))
            for index, key in enumerate(keys):
                if index >= 3000:
                    break
                result.add(key.removeprefix(prefix).partition(":")[0])
        except valkey.exceptions.ValkeyError:
            logger.warning("Service membership temporarily unavailable")
        return frozenset(result)
