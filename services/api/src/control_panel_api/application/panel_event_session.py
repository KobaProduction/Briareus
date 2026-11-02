"""One live channel's authority refresh, independent owner relay and bounded receive window."""

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from control_panel_api.domain.panel_protocol import PanelContext

from .panel_channel import (
    ChannelDisconnected,
    ContextSnapshot,
    ContextUnavailable,
    ControlNotice,
    PanelAuthority,
    PanelChannel,
    PanelEmitter,
    PanelEvent,
    PanelJournal,
)
from .panel_requests import PanelRequests


@dataclass(slots=True)
class ChannelReads:
    incoming: asyncio.Task[str]
    outgoing: asyncio.Task[PanelEvent]


@dataclass(slots=True)
class PanelEventSession[ModuleReply]:
    authority: PanelAuthority
    channel: PanelChannel[ModuleReply]
    emitter: PanelEmitter[ModuleReply]
    journal: PanelJournal
    requests: PanelRequests[ModuleReply]
    project: UUID | None
    latest: PanelContext | None = None

    async def relay_owners(self) -> None:
        while True:
            context = self.latest
            if context is not None and context.proof.expires_at > datetime.now(UTC):
                try:
                    await self.journal.relay_owners(context.proof)
                except Exception:
                    await self.journal.resync("owner.read_failed")
            await asyncio.sleep(1)

    async def unavailable(self, failure: ContextUnavailable) -> None:
        if failure.status == 401:
            await self.emitter.event(ControlNotice("session.refresh"))
            await self.channel.close(4401)
        elif failure.status == 403:
            await self.channel.close(4403)
        else:
            await self.emitter.event(ControlNotice("source.unavailable"))
            await self.channel.close(1013)

    async def snapshot(self, context: PanelContext) -> PanelContext:
        proof = replace(
            context.proof, expires_at=min(context.proof.expires_at, context.session.expires_at)
        )
        bounded = PanelContext(context.session, proof)
        self.latest = bounded
        now = datetime.now(UTC)
        await self.emitter.event(ContextSnapshot(bounded, now))
        if (context.session.expires_at - now).total_seconds() < 60:
            await self.emitter.event(ControlNotice("session.refresh"))
        return bounded

    async def incoming(self, reads: ChannelReads, context: PanelContext, messages: int) -> bool:
        raw = reads.incoming.result()
        if len(raw) > 32768:
            await self.channel.close(1009)
            return False
        try:
            request = self.requests.protocol.request(raw, messages)
            if not await self.requests.dispatch(request, context):
                return False
        except (ValueError, TypeError):
            await self.channel.close(1008)
            return False
        reads.incoming = asyncio.create_task(self.channel.receive())
        return True

    async def outgoing(self, reads: ChannelReads, context: PanelContext) -> bool:
        event = reads.outgoing.result()
        if (
            event.topic in self.requests.topics
            and self.journal.visible(event, context.proof)
            and min(context.proof.expires_at, context.session.expires_at) > datetime.now(UTC)
        ):
            await self.emitter.event(event)
        reads.outgoing = asyncio.create_task(self.journal.receive())
        return event.topic == "management.events"

    async def window(self, reads: ChannelReads, context: PanelContext) -> bool:
        loop = asyncio.get_running_loop()
        interval = min(
            5, max(0.1, (context.proof.expires_at - datetime.now(UTC)).total_seconds() / 2)
        )
        deadline, messages = loop.time() + interval, 0
        while (remaining := deadline - loop.time()) > 0:
            done, _ = await asyncio.wait(
                {reads.incoming, reads.outgoing},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                break
            if reads.incoming in done:
                messages += 1
                if not await self.incoming(reads, context, messages):
                    return False
            if reads.outgoing in done and await self.outgoing(reads, context):
                deadline = loop.time()
        return True

    async def run(self, initial: PanelContext) -> None:
        owner_task = asyncio.create_task(self.relay_owners(), name="panel-owner-signals")
        reads = ChannelReads(
            asyncio.create_task(self.channel.receive()), asyncio.create_task(self.journal.receive())
        )
        context: PanelContext | ContextUnavailable = initial
        try:
            while True:
                if isinstance(context, ContextUnavailable):
                    await self.unavailable(context)
                    return
                bounded = await self.snapshot(context)
                if not await self.window(reads, bounded):
                    return
                context = await self.authority.current(self.project)
        except (ChannelDisconnected, RuntimeError):
            pass
        finally:
            tasks = (reads.incoming, reads.outgoing, owner_task, *self.requests.modules)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
