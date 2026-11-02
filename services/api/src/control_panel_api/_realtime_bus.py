"""Valkey fanout adapter and composition for scoped realtime journal use cases."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from valkey.asyncio import Valkey
from valkey.asyncio.client import PubSub
from valkey.exceptions import ValkeyError

from control_panel_api.infrastructure.valkey_scripts import eval_script

from .application.realtime_journal import RealtimeJournal, resync_event
from .domain.panel_protocol import REALTIME_TOPICS as REALTIME_TOPICS
from .domain.platform_authority import ResolvedPlatformUser
from .domain.realtime_events import EventHistory, EventScope, RealtimeEvent, event_visible
from .domain.realtime_payloads import (
    BrowserOperation,
    PanelCall,
    ProcessMetrics,
    RealtimeData,
    RuntimeStatus,
)
from .infrastructure.realtime_codec import decode_event, encode_event
from .infrastructure.realtime_journal import JOURNAL, ValkeyEventJournal

_CHANNEL = "briareus:panel:events:fanout"
_LOG = logging.getLogger(__name__)
_EMIT = (
    "if ARGV[2]~='' and redis.call('EXISTS',KEYS[3])==1 then return '' end "
    "local id=redis.call('XADD',KEYS[1],'MAXLEN',20000,'*','event',ARGV[1]); "
    "local event=cjson.decode(ARGV[1]); event.cursor=id; "
    "redis.call('PUBLISH',KEYS[2],cjson.encode(event)); "
    "if ARGV[2]~='' then redis.call('SET',KEYS[3],id,'EX',90000) end return id"
)


class PubSubClose(Protocol):
    async def aclose(self) -> None: ...


class PanelEvents:
    def __init__(self) -> None:
        self.listeners: set[asyncio.Queue[RealtimeEvent]] = set()
        self.client: Valkey | None = None
        self.task: asyncio.Task[None] | None = None
        self.pubsub: PubSub | None = None
        self.metrics_task: asyncio.Task[None] | None = None
        self.started_at = time.monotonic()
        self._store = ValkeyEventJournal()
        self._journal = RealtimeJournal(self._store)

    async def start(self, client: Valkey) -> None:
        self.client = client
        self.pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            await self.pubsub.subscribe(_CHANNEL)
        except ValkeyError:
            _LOG.warning("realtime broker unavailable at startup")
        self.task = asyncio.create_task(self._listen(self.pubsub), name="panel-realtime-fanout")
        self.metrics_task = asyncio.create_task(self._metrics(), name="panel-realtime-metrics")

    async def close(self) -> None:
        tasks = tuple(task for task in (self.metrics_task, self.task) if task is not None)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.pubsub is not None:
            closer: PubSubClose = self.pubsub
            await closer.aclose()
        self.task = None
        self.pubsub = None
        self.client = None
        self.metrics_task = None
        self._store.client = None

    async def _metrics(self) -> None:
        import resource

        while True:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            await self.emit(
                "system.metrics",
                "process.snapshot",
                ProcessMetrics(
                    "control-panel-api",
                    round(time.monotonic() - self.started_at),
                    usage.ru_utime,
                    usage.ru_stime,
                    usage.ru_maxrss,
                ),
                visibility=EventScope("operator"),
            )
            await asyncio.sleep(10)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[RealtimeEvent]]:
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=256)
        self.listeners.add(queue)
        try:
            yield queue
        finally:
            self.listeners.discard(queue)

    def _fanout(self, event: RealtimeEvent) -> None:
        for queue in tuple(self.listeners):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(resync_event())
            queue.put_nowait(event)

    async def _listen(self, pubsub: PubSub) -> None:
        while True:
            try:
                message = await pubsub.get_message(timeout=1)
                if (
                    message
                    and isinstance(message.get("data"), str)
                    and len(message["data"]) <= 16384
                ):
                    event = decode_event(message["data"])
                    if event.topic in REALTIME_TOPICS:
                        self._fanout(event)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except (ValkeyError, ValueError, TypeError):
                _LOG.warning("realtime broker reconnecting")
                await asyncio.sleep(1)
                with suppress(ValkeyError):
                    await pubsub.subscribe(_CHANNEL)

    @staticmethod
    def resync(reason: str) -> RealtimeEvent:
        return resync_event(reason)

    async def emit(
        self,
        topic: str,
        event_type: str,
        data: RealtimeData,
        *,
        visibility: EventScope,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        if topic not in REALTIME_TOPICS:
            raise ValueError("Supported scoped event required")
        event = RealtimeEvent(
            topic,
            event_type,
            occurred_at or datetime.now(UTC),
            data,
            scope=visibility,
            event_id=event_id or str(uuid4()),
            version=1,
        )
        encoded = encode_event(event)
        if len(encoded) > 8192:
            raise ValueError("Event metadata too large")
        if self.client is None:
            self._fanout(event)
            return
        try:
            await eval_script(
                self.client,
                _EMIT,
                3,
                JOURNAL,
                _CHANNEL,
                JOURNAL + ":seen:" + (event_id or "ephemeral"),
                encoded,
                event_id or "",
            )
        except ValkeyError:
            _LOG.warning("realtime event broker unavailable")
            self._fanout(event)

    @staticmethod
    def visible(event: RealtimeEvent, proof: ResolvedPlatformUser) -> bool:
        return event_visible(event, proof)

    async def replay(
        self,
        *,
        proof: ResolvedPlatformUser,
        topics: set[str],
        cursor: str | None = None,
    ) -> tuple[RealtimeEvent, ...]:
        self._store.client = self.client
        return await self._journal.replay(proof=proof, topics=topics, cursor=cursor)

    async def history(
        self,
        *,
        proof: ResolvedPlatformUser,
        topics: set[str],
        before: str | None = None,
        project: str | None = None,
        limit: int = 100,
    ) -> EventHistory:
        self._store.client = self.client
        return await self._journal.history(
            proof=proof,
            topics=topics,
            before=before,
            project=project,
            limit=limit,
        )

    async def publish(
        self,
        *,
        actor: UUID,
        project: UUID,
        hand: str,
        tool: str,
        operation: UUID,
        status: RuntimeStatus,
        duration_ms: int | float,
    ) -> None:
        visibility = EventScope("project", id=project)
        await self.emit(
            "mcp.calls",
            "call." + status,
            PanelCall(actor, project, hand, tool, operation, status, duration_ms),
            visibility=visibility,
        )
        if hand == "web":
            await self.emit(
                "browser.runtime",
                "operation." + status,
                BrowserOperation(project, operation, tool, status),
                visibility=visibility,
            )
