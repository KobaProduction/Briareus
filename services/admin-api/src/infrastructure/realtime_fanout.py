"""Valkey SDK values are decoded here and never enter subscription queues."""

from typing import Protocol, cast

import valkey
from valkey.client import PubSub

from common.settings import ValkeySettings

from .realtime_codec import RealtimePublication


class _PubSubFactory(Protocol):
    """The installed synchronous SDK omits annotations on these two methods."""

    def pubsub(self, *, ignore_subscribe_messages: bool) -> PubSub: ...


class _SubscriptionCommand(Protocol):
    def subscribe(self, channel: str) -> None: ...


class ValkeyFanout:
    def __init__(self, channel: str, settings: ValkeySettings) -> None:
        self.channel = channel
        self._client = valkey.Valkey.from_url(
            settings.url,
            decode_responses=True,
            socket_connect_timeout=settings.socket_connect_timeout_seconds,
            socket_timeout=max(1.0, settings.socket_timeout_seconds),
            health_check_interval=30,
        )

    def publish(self, publication: RealtimePublication) -> None:
        self._client.publish(self.channel, publication.model_dump_json(exclude_unset=True))

    def open(self) -> PubSub:
        return cast(_PubSubFactory, self._client).pubsub(ignore_subscribe_messages=True)

    def subscribe(self, subscription: PubSub) -> None:
        cast(_SubscriptionCommand, subscription).subscribe(self.channel)

    @staticmethod
    def receive(subscription: PubSub) -> RealtimePublication | None:
        message: object = subscription.get_message(timeout=1.0)
        raw = message.get("data") if isinstance(message, dict) else None
        if not isinstance(raw, str):
            return None
        return RealtimePublication.model_validate_json(raw)

    @staticmethod
    def close(subscription: PubSub) -> None:
        subscription.close()
