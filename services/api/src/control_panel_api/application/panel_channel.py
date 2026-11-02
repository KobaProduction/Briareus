"""Typed ports and ordered outbound frames for one authenticated Panel channel."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from control_panel_api.application.module_contracts import HumanModuleReply
from control_panel_api.application.node_contracts import NodeOutput
from control_panel_api.application.platform_projection import PlatformContextPayload
from control_panel_api.domain.agent_directory import AgentDirectory
from control_panel_api.domain.panel_protocol import (
    HistorySelection,
    PanelContext,
    TopicSelection,
)
from control_panel_api.domain.panel_protocol import RpcFault as RpcFault
from control_panel_api.domain.platform_authority import ResolvedPlatformUser
from control_panel_api.domain.platform_management import ManagementOutput
from control_panel_api.domain.realtime_events import EventHistory, RealtimeEvent

from .panel_commands import RpcRequest

PanelEvent = RealtimeEvent


@dataclass(frozen=True, slots=True)
class ContextUnavailable:
    status: int


@dataclass(frozen=True, slots=True)
class RpcValue[Payload]:
    value: Payload


@dataclass(frozen=True, slots=True)
class RpcReply[ModuleReply]:
    identifier: str
    outcome: RpcValue[RpcPayload[ModuleReply]] | RpcFault


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    context: PanelContext
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ControlNotice:
    type: Literal["session.refresh", "source.unavailable"]


type PanelNotice = PanelEvent | ContextSnapshot | ControlNotice


@dataclass(frozen=True, slots=True)
class EventDelivery:
    notice: PanelNotice
    stream_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
class TopicsReply:
    topics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PongReply:
    occurredAt: str


type RpcPayload[ModuleReply] = (
    TopicsReply
    | PongReply
    | PlatformContextPayload
    | EventHistory
    | AgentDirectory
    | ManagementOutput
    | NodeOutput
    | HumanModuleReply[ModuleReply]
)


class ChannelDisconnected(Exception):
    """The browser transport closed while receiving or delivering a frame."""


class PanelChannel[ModuleReply](Protocol):
    async def receive(self) -> str: ...

    async def event(self, delivery: EventDelivery) -> None: ...

    async def reply(self, reply: RpcReply[ModuleReply]) -> None: ...

    async def close(self, code: int) -> None: ...


class PanelAuthority(Protocol):
    async def current(self, project: UUID | None = None) -> PanelContext | ContextUnavailable: ...

    async def user(self, project: UUID | None) -> RpcValue[PlatformContextPayload] | RpcFault: ...


class PanelJournal(Protocol):
    async def receive(self) -> PanelEvent: ...

    async def relay_owners(self, proof: ResolvedPlatformUser) -> None: ...

    async def resync(self, reason: str) -> None: ...

    async def replay(
        self, proof: ResolvedPlatformUser, selection: TopicSelection
    ) -> tuple[PanelEvent, ...]: ...

    async def history(
        self, proof: ResolvedPlatformUser, selection: HistorySelection
    ) -> RpcValue[EventHistory]: ...

    def visible(self, event: PanelEvent, proof: ResolvedPlatformUser) -> bool: ...


class PanelProtocol(Protocol):
    def request(self, raw: str, messages: int) -> RpcRequest: ...


class PanelFacade[ModuleReply](Protocol):
    async def call(self, request: RpcRequest) -> RpcValue[RpcPayload[ModuleReply]] | RpcFault: ...


@dataclass(slots=True)
class PanelEmitter[ModuleReply]:
    """RPC replies share the send lock but never consume event sequence numbers."""

    channel: PanelChannel[ModuleReply]
    stream_id: str = field(default_factory=lambda: str(uuid4()))
    sequence: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def event(self, notice: PanelNotice) -> None:
        async with self.lock:
            self.sequence += 1
            await self.channel.event(EventDelivery(notice, self.stream_id, self.sequence))

    async def reply(
        self, request: RpcRequest, outcome: RpcValue[RpcPayload[ModuleReply]] | RpcFault
    ) -> None:
        async with self.lock:
            await self.channel.reply(RpcReply(request.identifier, outcome))
