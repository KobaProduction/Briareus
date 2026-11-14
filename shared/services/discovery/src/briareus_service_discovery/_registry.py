import logging
import time
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
    connect_timeout_seconds: float = Field(
        1.0, ge=0.1, le=5.0, validation_alias="VALKEY_REGISTRY_CONNECT_TIMEOUT_SECONDS"
    )
    socket_timeout_seconds: float = Field(
        1.0, ge=0.1, le=5.0, validation_alias="VALKEY_REGISTRY_SOCKET_TIMEOUT_SECONDS"
    )
    failure_grace_seconds: float = Field(
        15.0, ge=0, le=300, validation_alias="VALKEY_REGISTRY_FAILURE_GRACE_SECONDS"
    )
    warning_interval_seconds: float = Field(
        300.0, ge=15, le=3600, validation_alias="VALKEY_REGISTRY_WARNING_INTERVAL_SECONDS"
    )


class ServiceRegistry:
    """Node-scoped inventory persists; each running instance has a short lease."""

    def __init__(self, settings: ValkeySettings | None = None) -> None:
        cache = settings or ValkeySettings()
        registry = RegistrySettings()
        self.environment = registry.environment
        self.prefix = f"{cache.namespace}:services:{self.environment}:"
        self._failure_grace_seconds = registry.failure_grace_seconds
        self._warning_interval_seconds = registry.warning_interval_seconds
        self._failure_started_at: float | None = None
        self._last_warning_at: float | None = None
        self._failed_attempts = 0
        self.client = valkey.Valkey.from_url(
            cache.url,
            username=cache.username,
            password=cache.password,
            decode_responses=True,
            socket_connect_timeout=registry.connect_timeout_seconds,
            socket_timeout=registry.socket_timeout_seconds,
            health_check_interval=30,
        )

    def _announce_failed(self, service: ServiceDefinition, error: Exception) -> None:
        now = time.monotonic()
        if self._failure_started_at is None:
            self._failure_started_at = now
        self._failed_attempts += 1
        duration = now - self._failure_started_at
        if duration < self._failure_grace_seconds:
            logger.debug("Service lease retry pending service=%s", service.id)
            return
        if (
            self._last_warning_at is None
            or now - self._last_warning_at >= self._warning_interval_seconds
        ):
            logger.warning(
                "Service registration unavailable service=%s reason=%s "
                "failed_attempts=%d outage_seconds=%.1f",
                service.id, type(error).__name__, self._failed_attempts, duration,
            )
            self._last_warning_at = now

    def _announce_recovered(self, service: ServiceDefinition) -> None:
        if self._failure_started_at is None:
            return
        duration = time.monotonic() - self._failure_started_at
        logger.info(
            "Service registration recovered service=%s failed_attempts=%d "
            "outage_seconds=%.1f",
            service.id, self._failed_attempts, duration,
        )
        self._failure_started_at = None
        self._last_warning_at = None
        self._failed_attempts = 0

    def announce(self, service: ServiceDefinition, instance: str) -> None:
        try:
            # Both SETs share one network round trip; inventory is durable,
            # whereas the lease is still strictly limited to 20 seconds.
            with self.client.pipeline(transaction=False) as pipeline:
                pipeline.set(self.prefix + "inventory:" + service.id, service.model_dump_json())
                pipeline.set(self.prefix + f"lease:{service.id}:{instance}", "1", ex=20)
                cast(Callable[[], object], pipeline.execute)()
        except valkey.exceptions.ValkeyError as exc:
            self._announce_failed(service, exc)
        else:
            self._announce_recovered(service)

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
