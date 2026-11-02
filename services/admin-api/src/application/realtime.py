"""Connection-scoped subscription ordering and paired stream task lifetime."""

import asyncio
from typing import Literal, Protocol

from domain.realtime import REALTIME_TOPICS, RealtimeCommand, validate_topic

SubscriptionReply = Literal["ready", "subscribed", "unsubscribed"]


class RealtimeConnection(Protocol):
    async def receive(self) -> RealtimeCommand | None: ...
    async def acknowledge(self, kind: SubscriptionReply, topics: tuple[str, ...]) -> None: ...
    async def invalid_topic(self, message: str) -> None: ...
    async def pong(self) -> None: ...
    async def send_snapshot(self, topic: str) -> None: ...
    async def send_next_event(self) -> None: ...


class RealtimeSession:
    def __init__(self, connection: RealtimeConnection, topics: set[str]) -> None:
        self._connection = connection
        self._topics = topics

    async def run(self) -> None:
        await self._connection.acknowledge("ready", tuple(sorted(REALTIME_TOPICS)))
        tasks = (
            asyncio.create_task(self._receive_commands()),
            asyncio.create_task(self._send_events()),
        )
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _receive_commands(self) -> None:
        while True:
            command = await self._connection.receive()
            if command is not None:
                await self._dispatch(command)

    async def _dispatch(self, command: RealtimeCommand) -> None:
        if command.kind == "subscribe":
            await self._subscribe(command.topics)
        elif command.kind == "unsubscribe":
            self._topics.difference_update(command.topics)
            await self._connection.acknowledge("unsubscribed", tuple(sorted(self._topics)))
        elif command.kind == "ping":
            await self._connection.pong()

    async def _subscribe(self, requested: tuple[str, ...]) -> None:
        try:
            topics = tuple(validate_topic(topic) for topic in requested)
        except ValueError as exc:
            await self._connection.invalid_topic(str(exc))
            return
        # Validate the entire batch before changing the bus's active subscription.
        self._topics.update(topics)
        await self._connection.acknowledge("subscribed", tuple(sorted(self._topics)))
        for topic in topics:
            await self._connection.send_snapshot(topic)

    async def _send_events(self) -> None:
        while True:
            await self._connection.send_next_event()
