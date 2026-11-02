from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field

import valkey
from application.realtime_details import RealtimeDetails
from domain.realtime import REALTIME_TOPICS as REALTIME_TOPICS
from domain.realtime import MetricsHeartbeat, validate_topic
from infrastructure.realtime_codec import REALTIME_VERSION as REALTIME_VERSION
from infrastructure.realtime_codec import RealtimeEnvelope as RealtimeEnvelope
from infrastructure.realtime_codec import RealtimePublication, new_event
from infrastructure.realtime_fanout import ValkeyFanout
from valkey.client import PubSub

from common.cache import SharedCache
from common.settings import ValkeySettings

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class RealtimeSubscriber:
    queue: asyncio.Queue[RealtimeEnvelope] = field(
        default_factory=lambda: asyncio.Queue(maxsize=256)
    )
    topics: set[str] = field(default_factory=set)


class RealtimeBus:
    """Process-local subscribers with best-effort Valkey fanout and snapshot cache."""

    def __init__(self, cache: SharedCache, settings: ValkeySettings) -> None:
        self.cache = cache
        self.settings = settings
        self.channel = cache.key("realtime", "fanout")
        self.source_id = uuid.uuid4().hex
        self._subscribers: set[RealtimeSubscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._fanout = ValkeyFanout(self.channel, settings)

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(
                self._listen(), name="admin-api-realtime-valkey"
            )

    async def close(self) -> None:
        task = self._listener_task
        self._listener_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def register(self) -> RealtimeSubscriber:
        subscriber = RealtimeSubscriber()
        self._subscribers.add(subscriber)
        return subscriber

    def unregister(self, subscriber: RealtimeSubscriber) -> None:
        self._subscribers.discard(subscriber)

    @staticmethod
    def validate_topic(topic: str) -> str:
        return validate_topic(topic)

    def snapshot(self, topic: str) -> RealtimeEnvelope | None:
        topic = self.validate_topic(topic)
        cached = self.cache.get_model(
            self.cache.key("realtime", "snapshot", topic), RealtimeEnvelope
        )
        return cached if cached is not None and cached.topic == topic else None

    def _local_fanout(self, envelope: RealtimeEnvelope) -> None:
        for subscriber in tuple(self._subscribers):
            if envelope.topic not in subscriber.topics:
                continue
            if subscriber.queue.full():
                with suppress(asyncio.QueueEmpty):
                    subscriber.queue.get_nowait()
            with suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(envelope)

    def _prepare_envelope(
        self, topic: str, event_type: str, data: RealtimeDetails
    ) -> RealtimeEnvelope:
        envelope = new_event(topic, event_type, data)
        self.cache.set_model(
            self.cache.key("realtime", "snapshot", envelope.topic),
            envelope,
            ttl_seconds=60,
            exclude_unset=True,
        )
        return envelope

    def publish_sync(self, topic: str, event_type: str, data: RealtimeDetails) -> None:
        envelope = self._prepare_envelope(topic, event_type, data)
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._local_fanout, envelope)
        try:
            self._fanout.publish(RealtimePublication(source=self.source_id, event=envelope))
        except valkey.exceptions.ValkeyError:
            logger.warning("realtime Valkey publish failed; using local fallback")

    async def publish(self, topic: str, event_type: str, data: RealtimeDetails) -> RealtimeEnvelope:
        envelope = self._prepare_envelope(topic, event_type, data)
        self._local_fanout(envelope)
        publication = RealtimePublication(source=self.source_id, event=envelope)
        try:
            await asyncio.to_thread(self._fanout.publish, publication)
        except valkey.exceptions.ValkeyError:
            logger.warning("realtime Valkey publish failed; using local fallback")
        return envelope

    async def _listen(self) -> None:
        backoff = 0.5
        while True:
            pubsub: PubSub | None = None
            try:
                pubsub = self._fanout.open()
                await asyncio.to_thread(self._fanout.subscribe, pubsub)
                backoff = 0.5
                await self._receive_remote(pubsub)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("realtime Valkey subscriber unavailable; retrying", exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(5.0, backoff * 2)
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await asyncio.to_thread(self._fanout.close, pubsub)

    async def _receive_remote(self, pubsub: PubSub) -> None:
        while True:
            publication = await asyncio.to_thread(self._fanout.receive, pubsub)
            if publication is None:
                await asyncio.sleep(0)
                continue
            self._consume_remote(publication)

    def _consume_remote(self, publication: RealtimePublication) -> None:
        if publication.source != self.source_id:
            self._local_fanout(publication.event)


async def periodic_metrics(bus: RealtimeBus, *, interval_seconds: float = 5.0) -> None:
    while True:
        await bus.publish("system.metrics", "heartbeat", MetricsHeartbeat(time.monotonic()))
        await asyncio.sleep(interval_seconds)
