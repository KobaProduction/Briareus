"""Realtime subscriptions, journal authority continuity and bounded module requests."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from control_panel_api.domain.panel_protocol import (
    MODULE_METHODS,
    PLATFORM_METHODS,
    REALTIME_TOPICS,
    HistorySelection,
    PanelContext,
    TopicSelection,
    same_authority,
)

from .panel_channel import (
    ContextUnavailable,
    PanelAuthority,
    PanelChannel,
    PanelEmitter,
    PanelFacade,
    PanelJournal,
    PanelProtocol,
    PongReply,
    RpcFault,
    RpcValue,
    TopicsReply,
)
from .panel_commands import RpcRequest


@dataclass(slots=True)
class PanelRequests[ModuleReply]:
    authority: PanelAuthority
    channel: PanelChannel[ModuleReply]
    emitter: PanelEmitter[ModuleReply]
    journal: PanelJournal
    protocol: PanelProtocol
    facade: PanelFacade[ModuleReply]
    project: UUID | None
    topics: set[str] = field(default_factory=lambda: set(REALTIME_TOPICS))
    modules: set[asyncio.Task[None]] = field(default_factory=set)

    async def subscription(self, request: RpcRequest, context: PanelContext) -> bool:
        selection = request.command_as(TopicSelection)
        if request.method == "events.subscribe":
            self.topics.update(selection.topics)
            for event in await self.journal.replay(context.proof, selection):
                if context.proof.expires_at <= datetime.now(UTC):
                    await self.channel.close(1013)
                    return False
                await self.emitter.event(event)
        else:
            self.topics.difference_update(selection.topics)
        await self.emitter.reply(request, RpcValue(TopicsReply(tuple(sorted(self.topics)))))
        return True

    async def history(self, request: RpcRequest, context: PanelContext) -> None:
        # Shape errors remain protocol errors (close1008), not journal failures.
        selection = request.command_as(HistorySelection)
        try:
            result = await self.journal.history(context.proof, selection)
            fresh = await self.authority.current()
            if (
                isinstance(fresh, ContextUnavailable)
                or context.proof.expires_at <= datetime.now(UTC)
                or not same_authority(fresh, context)
            ):
                raise ValueError("JOURNAL_CONTEXT_CHANGED")
            await self.emitter.reply(request, result)
        except Exception:
            await self.emitter.reply(request, RpcFault("JOURNAL_UNAVAILABLE"))

    def module_finished(self, task: asyncio.Task[None]) -> None:
        self.modules.discard(task)
        if not task.cancelled():
            task.exception()

    async def module_reply(self, request: RpcRequest) -> None:
        try:
            await self.emitter.reply(request, await self.facade.call(request))
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.emitter.reply(request, RpcFault("MODULE_OWNER_UNAVAILABLE", uncertain=True))

    async def module(self, request: RpcRequest) -> None:
        if len(self.modules) >= 8:
            await self.emitter.reply(request, RpcFault("MODULE_REQUESTS_BUSY", uncertain=False))
            return
        task = asyncio.create_task(self.module_reply(request))
        self.modules.add(task)
        task.add_done_callback(self.module_finished)

    async def dispatch(self, request: RpcRequest, context: PanelContext) -> bool:
        method = request.method
        if method in {"events.subscribe", "events.unsubscribe"}:
            return await self.subscription(request, context)
        if method == "events.history":
            await self.history(request, context)
        elif method == "system.ping" and request.command == "empty":
            await self.emitter.reply(request, RpcValue(PongReply(datetime.now(UTC).isoformat())))
        elif method == "platform.current" and request.command == "empty":
            await self.emitter.reply(request, await self.authority.user(self.project))
        elif method in MODULE_METHODS:
            await self.module(request)
        elif method in PLATFORM_METHODS or method in {
            "agents.list",
            "agents.get",
            "nodes.inventory",
            "nodes.command",
        }:
            await self.emitter.reply(request, await self.facade.call(request))
        else:
            await self.emitter.reply(request, RpcFault("Method unavailable", code=-32601))
        return True
