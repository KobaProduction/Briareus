from __future__ import annotations

import logging
import threading
import time

import valkey
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, ValidationError

from .cache_contracts import CacheBackend as CacheBackend
from .cache_contracts import CacheKeys as CacheKeys
from .settings import ValkeySettings

logger = logging.getLogger(__name__)
_TRACER = trace.get_tracer("mcp-bridge.valkey-cache")


class SharedCache:
    """Best-effort shared cache backed by private, ephemeral Valkey."""

    def __init__(self, settings: ValkeySettings | None = None) -> None:
        self.settings = settings or ValkeySettings()
        self._client = valkey.Valkey.from_url(
            self.settings.url,
            decode_responses=True,
            socket_connect_timeout=self.settings.socket_connect_timeout_seconds,
            socket_timeout=self.settings.socket_timeout_seconds,
            health_check_interval=30,
        )
        self._availability_lock = threading.Lock()
        self._disabled_until = 0.0

    def _available(self) -> bool:
        with self._availability_lock:
            return time.monotonic() >= self._disabled_until

    def _mark_failed(self, exc: Exception) -> None:
        now = time.monotonic()
        with self._availability_lock:
            should_log = now >= self._disabled_until
            self._disabled_until = now + self.settings.failure_backoff_seconds
        if should_log:
            logger.warning(
                "Valkey cache temporarily bypassed backoff_seconds=%.1f error=%s",
                self.settings.failure_backoff_seconds,
                type(exc).__name__,
            )

    def _mark_available(self) -> None:
        with self._availability_lock:
            self._disabled_until = 0.0

    def key(self, *parts: str) -> str:
        normalized = [self.settings.namespace.rstrip(":")]
        normalized.extend(part.strip().casefold() for part in parts if part.strip())
        return ":".join(normalized)

    def get_model[T: BaseModel](self, key: str, model: type[T]) -> T | None:
        if not self._available():
            return None
        with _TRACER.start_as_current_span(
            "cache.get",
            kind=SpanKind.CLIENT,
            attributes={"cache.system": "valkey", "cache.namespace": self.settings.namespace},
        ) as span:
            try:
                raw: object = self._client.get(key)
            except valkey.exceptions.ValkeyError as exc:
                span.record_exception(exc)
                span.set_attribute("cache.available", False)
                self._mark_failed(exc)
                return None
            self._mark_available()
            span.set_attribute("cache.available", True)
            span.set_attribute("cache.hit", raw is not None)
            if raw is None:
                return None
            try:
                if not isinstance(raw, (str, bytes)):
                    self.delete(key)
                    return None
                return model.model_validate_json(raw)
            except ValidationError:
                self.delete(key)
                return None

    def set_model(
        self, key: str, value: BaseModel, *, ttl_seconds: int, exclude_unset: bool = False
    ) -> bool:
        if not self._available():
            return False
        encoded = value.model_dump_json(exclude_unset=exclude_unset)
        with _TRACER.start_as_current_span(
            "cache.set",
            kind=SpanKind.CLIENT,
            attributes={
                "cache.system": "valkey",
                "cache.namespace": self.settings.namespace,
                "cache.ttl_seconds": ttl_seconds,
            },
        ) as span:
            try:
                self._client.set(key, encoded, ex=max(1, ttl_seconds))
            except valkey.exceptions.ValkeyError as exc:
                span.record_exception(exc)
                span.set_attribute("cache.available", False)
                self._mark_failed(exc)
                return False
            self._mark_available()
            span.set_attribute("cache.available", True)
            return True

    def delete(self, *keys: str) -> bool:
        values = tuple(key for key in keys if key)
        if not values:
            return True
        if not self._available():
            return False
        with _TRACER.start_as_current_span(
            "cache.delete",
            kind=SpanKind.CLIENT,
            attributes={"cache.system": "valkey", "cache.key_count": len(values)},
        ) as span:
            try:
                self._client.delete(*values)
            except valkey.exceptions.ValkeyError as exc:
                span.record_exception(exc)
                span.set_attribute("cache.available", False)
                self._mark_failed(exc)
                return False
            self._mark_available()
            span.set_attribute("cache.available", True)
            return True

    def ping(self) -> bool:
        try:
            result = bool(self._client.ping())
        except valkey.exceptions.ValkeyError as exc:
            self._mark_failed(exc)
            return False
        if result:
            self._mark_available()
        return result
