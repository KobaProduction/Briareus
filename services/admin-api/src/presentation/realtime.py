"""Existing WebSocket JSON adapted to typed commands and event envelopes."""

from typing import Literal

from application.realtime import SubscriptionReply
from domain.realtime import RealtimeCommand
from infrastructure.realtime_codec import event_json
from infrastructure.realtime_snapshots import LegacyRealtimeSnapshots
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from realtime import RealtimeSubscriber
from starlette.websockets import WebSocket


class SubscriptionMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str = Field(default="", alias="type")
    topic: str = ""
    topics: tuple[str, ...] | None = None

    @field_validator("kind", "topic", mode="before")
    @classmethod
    def text_field(cls, value: object) -> str:
        return str(value or "")

    @field_validator("topics", mode="before")
    @classmethod
    def topic_selection(cls, value: object) -> tuple[str, ...] | None:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, list):
            return tuple(str(item) for item in value)
        return None


class SubscriptionAcknowledgement(BaseModel):
    version: Literal[1] = 1
    type: SubscriptionReply
    topics: tuple[str, ...]


class InvalidTopicMessage(BaseModel):
    version: Literal[1] = 1
    type: Literal["error"] = "error"
    code: Literal["invalid_topic"] = "invalid_topic"
    message: str


class PongMessage(BaseModel):
    version: Literal[1] = 1
    type: Literal["pong"] = "pong"


def decode_command(value: object) -> RealtimeCommand | None:
    if not isinstance(value, dict):
        return None
    try:
        message = SubscriptionMessage.model_validate(value)
    except ValidationError:
        return None
    topics = message.topics
    if topics is None:
        topics = (message.topic,) if message.topic else ()
    return RealtimeCommand(message.kind, topics)


class JsonRealtimeConnection:
    def __init__(
        self,
        websocket: WebSocket,
        subscriber: RealtimeSubscriber,
        snapshots: LegacyRealtimeSnapshots,
    ) -> None:
        self._websocket = websocket
        self._subscriber = subscriber
        self._snapshots = snapshots

    async def receive(self) -> RealtimeCommand | None:
        message: object = await self._websocket.receive_json()
        return decode_command(message)

    async def acknowledge(self, kind: SubscriptionReply, topics: tuple[str, ...]) -> None:
        message = SubscriptionAcknowledgement(type=kind, topics=topics)
        await self._websocket.send_text(message.model_dump_json())

    async def invalid_topic(self, message: str) -> None:
        response = InvalidTopicMessage(message=message)
        await self._websocket.send_text(response.model_dump_json())

    async def pong(self) -> None:
        await self._websocket.send_text(PongMessage().model_dump_json())

    async def send_snapshot(self, topic: str) -> None:
        snapshot = await self._snapshots.read(topic)
        if snapshot is not None:
            await self._websocket.send_text(event_json(snapshot))

    async def send_next_event(self) -> None:
        event = await self._subscriber.queue.get()
        await self._websocket.send_text(event_json(event))
