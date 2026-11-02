"""Adapt the existing broker and scoped owner signals to a live Panel session."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from control_panel_api.application.owner_event_relay import RelayNotice
from control_panel_api.application.panel_channel import PanelEvent, RpcValue
from control_panel_api.domain.panel_protocol import HistorySelection, TopicSelection
from control_panel_api.domain.platform_authority import ResolvedPlatformUser
from control_panel_api.domain.realtime_events import EventHistory


class PanelBroker(Protocol):
    def visible(self, event: PanelEvent, proof: ResolvedPlatformUser) -> bool: ...

    def resync(self, reason: str) -> PanelEvent: ...

    async def replay(
        self,
        *,
        proof: ResolvedPlatformUser,
        topics: set[str],
        cursor: str | None,
    ) -> tuple[PanelEvent, ...]: ...

    async def history(
        self,
        *,
        proof: ResolvedPlatformUser,
        topics: set[str],
        before: str | None,
        project: str | None,
        limit: int,
    ) -> EventHistory: ...


class OwnerSignalSource(Protocol):
    def read(self, proof: ResolvedPlatformUser) -> AsyncIterator[RelayNotice]: ...


@dataclass(slots=True)
class PanelJournalAdapter:
    broker: PanelBroker
    queue: asyncio.Queue[PanelEvent]
    owners: OwnerSignalSource

    async def receive(self) -> PanelEvent:
        return await self.queue.get()

    async def relay_owners(self, proof: ResolvedPlatformUser) -> None:
        async for notice in self.owners.read(proof):
            await self.queue.put(notice)

    async def resync(self, reason: str) -> None:
        await self.queue.put(self.broker.resync(reason))

    async def replay(
        self, proof: ResolvedPlatformUser, selection: TopicSelection
    ) -> tuple[PanelEvent, ...]:
        return await self.broker.replay(
            proof=proof, topics=set(selection.topics), cursor=selection.cursor
        )

    async def history(
        self, proof: ResolvedPlatformUser, selection: HistorySelection
    ) -> RpcValue[EventHistory]:
        return RpcValue(
            await self.broker.history(
                proof=proof,
                topics=set(selection.topics),
                before=selection.before,
                project=selection.project,
                limit=selection.limit,
            )
        )

    def visible(self, event: PanelEvent, proof: ResolvedPlatformUser) -> bool:
        return self.broker.visible(event, proof)
