from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, Literal, Protocol, cast

import valkey
from briareus_cache.cache import SharedCache
from briareus_cache.settings import ValkeySettings
from briareus_json_values import JsonValue, StrictModel, json_value
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from control_panel_api.domain.events import EventData, MetricsHeartbeat, RealtimeTopic

logger = logging.getLogger(__name__)
REALTIME_VERSION: Final[int] = 1
REALTIME_TOPICS: Final[frozenset[RealtimeTopic]] = frozenset(
    {"mcp.calls", "system.metrics", "system.notifications", "browser.runtime", "management.events"}
)


class RealtimePubSub(Protocol):
    def subscribe(self, channel: str) -> None: ...
    def get_message(self, *, timeout: float) -> object: ...
    def close(self) -> None: ...


class RealtimePubSubFactory(Protocol):
    def pubsub(self, *, ignore_subscribe_messages: bool) -> RealtimePubSub: ...


class RealtimeEnvelope(StrictModel):
    version: Literal[1] = 1
    topic: RealtimeTopic
    type: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.]*$")
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: JsonValue

    @classmethod
    def create(cls, topic: str, event_type: str, data: EventData) -> RealtimeEnvelope:
        serialized = (
            data.model_dump(mode="json", exclude_unset=True)
            if isinstance(data, BaseModel)
            else data
        )
        return cls(
            topic=TypeAdapter(RealtimeTopic).validate_python(topic),
            type=event_type,
            data=json_value(serialized, context="realtime data"),
        )


class RealtimeFanout(StrictModel):
    source: str
    event: RealtimeEnvelope


@dataclass(eq=False)
class RealtimeSubscriber:
    queue: asyncio.Queue[RealtimeEnvelope] = field(
        default_factory=lambda: asyncio.Queue(maxsize=256)
    )
    topics: set[RealtimeTopic] = field(default_factory=set)


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
        self._redis = valkey.Valkey.from_url(
            settings.url,
            username=settings.username,
            password=settings.password,
            decode_responses=True,
            socket_connect_timeout=settings.socket_connect_timeout_seconds,
            socket_timeout=max(1.0, settings.socket_timeout_seconds),
            health_check_interval=30,
        )

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(
                self._listen(), name="control-panel-realtime-valkey"
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
    def validate_topic(topic: str) -> RealtimeTopic:
        try:
            return TypeAdapter(RealtimeTopic).validate_python(topic.strip())
        except ValidationError as exc:
            raise ValueError(f"unsupported realtime topic: {topic}") from exc

    def snapshot(self, topic: str) -> RealtimeEnvelope | None:
        validated = self.validate_topic(topic)
        cached = self.cache.get_json(self.cache.key("realtime", "snapshot", validated))
        return (
            RealtimeEnvelope.model_validate_json(json.dumps(cached)) if cached is not None else None
        )

    def _local_fanout(self, envelope: RealtimeEnvelope) -> None:
        for subscriber in tuple(self._subscribers):
            if envelope.topic not in subscriber.topics:
                continue
            if subscriber.queue.full():
                with suppress(asyncio.QueueEmpty):
                    subscriber.queue.get_nowait()
            with suppress(asyncio.QueueFull):
                subscriber.queue.put_nowait(envelope)

    def _cache_envelope(self, envelope: RealtimeEnvelope) -> None:
        self.cache.set_json(
            self.cache.key("realtime", "snapshot", envelope.topic),
            envelope.to_json(),
            ttl_seconds=60,
        )

    def publish_sync(self, topic: str, event_type: str, data: EventData) -> RealtimeEnvelope:
        envelope = RealtimeEnvelope.create(self.validate_topic(topic), event_type, data)
        self._cache_envelope(envelope)
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._local_fanout, envelope)
        try:
            self._redis.publish(
                self.channel,
                RealtimeFanout(source=self.source_id, event=envelope).model_dump_json(),
            )
        except valkey.exceptions.ValkeyError:
            logger.warning("realtime Valkey publish failed; using local fallback")
        return envelope

    async def publish(self, topic: str, event_type: str, data: EventData) -> RealtimeEnvelope:
        envelope = RealtimeEnvelope.create(self.validate_topic(topic), event_type, data)
        self._cache_envelope(envelope)
        self._local_fanout(envelope)
        encoded = RealtimeFanout(source=self.source_id, event=envelope).model_dump_json()
        try:
            await asyncio.to_thread(self._redis.publish, self.channel, encoded)
        except valkey.exceptions.ValkeyError:
            logger.warning("realtime Valkey publish failed; using local fallback")
        return envelope

    async def _listen(self) -> None:
        backoff = 0.5
        while True:
            pubsub = None
            try:
                pubsub = cast(RealtimePubSubFactory, self._redis).pubsub(
                    ignore_subscribe_messages=True
                )
                await asyncio.to_thread(pubsub.subscribe, self.channel)
                backoff = 0.5
                await self._poll_messages(pubsub)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("realtime Valkey subscriber unavailable; retrying", exc_info=True)
                await asyncio.sleep(backoff)
                backoff = min(5.0, backoff * 2)
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await asyncio.to_thread(pubsub.close)

    def _receive_message(self, message: object) -> None:
        raw = message.get("data") if isinstance(message, dict) else None
        if not isinstance(raw, str):
            return
        try:
            fanout = RealtimeFanout.model_validate_json(raw)
        except ValidationError:
            logger.warning("discarded invalid realtime fanout message")
            return
        if fanout.source != self.source_id:
            self._local_fanout(fanout.event)

    async def _poll_messages(self, pubsub: RealtimePubSub) -> None:
        while True:
            message = await asyncio.to_thread(pubsub.get_message, timeout=1.0)
            if not message:
                await asyncio.sleep(0)
                continue
            self._receive_message(message)


async def periodic_metrics(bus: RealtimeBus, *, interval_seconds: float = 5.0) -> None:
    while True:
        await bus.publish(
            "system.metrics",
            "heartbeat",
            MetricsHeartbeat(monotonic_seconds=time.monotonic(), status="ok"),
        )
        await asyncio.sleep(interval_seconds)
