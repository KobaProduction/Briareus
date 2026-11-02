from __future__ import annotations

import asyncio
import logging
import uuid

import valkey

from common.access_contracts import (
    AccessLifecycleDetails,
    AccessLifecycleEvent,
    AccessLifecyclePublication,
    AccessLifecycleType,
)
from common.cache import SharedCache
from common.settings import ValkeySettings

logger = logging.getLogger(__name__)


class AccessEventPublisher:
    """Best-effort access lifecycle fanout onto the admin realtime channel."""

    def __init__(self, cache: SharedCache, settings: ValkeySettings) -> None:
        self.cache = cache
        self.channel = cache.key("realtime", "fanout")
        self.source_id = f"access:{uuid.uuid4().hex}"
        self._redis = valkey.Valkey.from_url(
            settings.url,
            decode_responses=True,
            socket_connect_timeout=settings.socket_connect_timeout_seconds,
            socket_timeout=settings.socket_timeout_seconds,
            health_check_interval=30,
        )

    async def close(self) -> None:
        await asyncio.to_thread(self._redis.close)

    async def publish(self, event_type: AccessLifecycleType, data: AccessLifecycleDetails) -> None:
        envelope = AccessLifecycleEvent(type=event_type, data=data)
        await asyncio.to_thread(
            self.cache.set_model,
            self.cache.key("realtime", "snapshot", "access.sessions"),
            envelope,
            ttl_seconds=60,
        )
        encoded = AccessLifecyclePublication(
            source=self.source_id, event=envelope
        ).model_dump_json()
        try:
            await asyncio.to_thread(self._redis.publish, self.channel, encoded)
        except valkey.exceptions.ValkeyError:
            logger.warning("access realtime Valkey publish failed")
