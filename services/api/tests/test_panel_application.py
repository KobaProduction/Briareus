"""Transport-independent acceptance for live channel scheduling and authority continuity."""

import asyncio
import unittest
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from control_panel_api.application.module_contracts import ModuleRequest
from control_panel_api.application.panel_channel import (
    ContextUnavailable,
    EventDelivery,
    PanelEmitter,
    PanelEvent,
    RpcFault,
    RpcPayload,
    RpcReply,
    RpcValue,
)
from control_panel_api.application.panel_commands import RpcRequest
from control_panel_api.application.panel_event_session import PanelEventSession
from control_panel_api.application.panel_requests import PanelRequests
from control_panel_api.application.platform_projection import PlatformContextPayload
from control_panel_api.domain.panel_protocol import (
    HistorySelection,
    PanelContext,
    TopicSelection,
)
from control_panel_api.domain.platform_authority import PanelOidcSession, ResolvedPlatformUser
from control_panel_api.domain.realtime_events import EventHistory
from control_panel_api.domain.realtime_payloads import PlatformMutation, ResyncRequired
from control_panel_api.presentation.panel_protocol import (
    DecodedPanelProtocol,
    history,
    request_frame,
    subscription,
)
from mcp_types import CallToolResult


def context(*, actor: UUID | None = None) -> PanelContext:
    now = datetime.now(UTC)
    session = PanelOidcSession(
        "https://identity.example", "subject", "panel", now + timedelta(minutes=10)
    )
    proof = ResolvedPlatformUser(
        session.issuer,
        session.subject,
        actor or uuid4(),
        True,
        "operator",
        now + timedelta(seconds=25),
        (),
        (),
    )
    return PanelContext(session, proof)


@dataclass
class ChannelFixture:
    incoming: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    deliveries: list[EventDelivery] = field(default_factory=list)
    replies: list[RpcReply[CallToolResult]] = field(default_factory=list)
    closed: list[int] = field(default_factory=list)

    async def receive(self) -> str:
        return await self.incoming.get()

    async def event(self, delivery: EventDelivery) -> None:
        self.deliveries.append(delivery)

    async def reply(self, reply: RpcReply[CallToolResult]) -> None:
        self.replies.append(reply)

    async def close(self, code: int) -> None:
        self.closed.append(code)


@dataclass
class AuthorityFixture:
    refreshed: PanelContext | ContextUnavailable

    async def current(self, project: UUID | None = None) -> PanelContext | ContextUnavailable:
        assert project is None
        return self.refreshed

    async def user(self, project: UUID | None) -> RpcValue[PlatformContextPayload] | RpcFault:
        del project
        raise AssertionError("Unexpected user projection in live-session fixture")


@dataclass
class JournalFixture:
    outgoing: asyncio.Queue[PanelEvent] = field(default_factory=asyncio.Queue)
    owner_entered: asyncio.Event = field(default_factory=asyncio.Event)

    async def receive(self) -> PanelEvent:
        return await self.outgoing.get()

    async def relay_owners(self, proof: ResolvedPlatformUser) -> None:
        assert proof.expires_at.tzinfo is not None
        self.owner_entered.set()
        await asyncio.Event().wait()

    async def resync(self, reason: str) -> None:
        await self.outgoing.put(
            PanelEvent(
                "system.notifications", "resync.required", datetime.now(UTC), ResyncRequired(reason)
            )
        )

    async def replay(
        self, proof: ResolvedPlatformUser, selection: TopicSelection
    ) -> tuple[PanelEvent, ...]:
        assert proof.expires_at.tzinfo is not None
        del selection
        raise AssertionError("Unexpected replay in live-session fixture")

    async def history(
        self, proof: ResolvedPlatformUser, selection: HistorySelection
    ) -> RpcValue[EventHistory]:
        assert proof.expires_at.tzinfo is not None
        del selection
        return RpcValue(EventHistory((), None, False, False))

    def visible(self, event: PanelEvent, proof: ResolvedPlatformUser) -> bool:
        return bool(event.topic) and proof.enabled


@dataclass
class FacadeFixture:
    release: asyncio.Event = field(default_factory=asyncio.Event)

    async def call(self, request: RpcRequest) -> RpcValue[RpcPayload[CallToolResult]]:
        del request
        await self.release.wait()
        return RpcValue(CallToolResult(content=[]))


def requests(
    channel: ChannelFixture,
    authority: AuthorityFixture,
    journal: JournalFixture,
) -> PanelRequests[CallToolResult]:
    return PanelRequests(
        authority,
        channel,
        PanelEmitter(channel),
        journal,
        DecodedPanelProtocol(),
        FacadeFixture(),
        None,
    )


class LiveSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_owner_does_not_block_ping_and_rpc_does_not_consume_sequence(self) -> None:
        initial = context()
        channel, journal = ChannelFixture(), JournalFixture()
        authority = AuthorityFixture(initial)
        handler = requests(channel, authority, journal)
        await channel.incoming.put(
            '{"jsonrpc":"2.0","id":"ping","method":"system.ping","params":{}}'
        )
        await channel.incoming.put("invalid")
        session = PanelEventSession(authority, channel, handler.emitter, journal, handler, None)
        await asyncio.wait_for(session.run(initial), 1)
        self.assertEqual(channel.closed, [1008])
        self.assertEqual([reply.identifier for reply in channel.replies], ["ping"])
        self.assertEqual([delivery.sequence for delivery in channel.deliveries], [1])
        self.assertTrue(journal.owner_entered.is_set())

    async def test_management_event_forces_fresh_authority_and_permission_denial_closes(
        self,
    ) -> None:
        initial = context()
        channel, journal = ChannelFixture(), JournalFixture()
        await journal.outgoing.put(
            PanelEvent(
                "management.events",
                "team.rename",
                datetime.now(UTC),
                PlatformMutation("team.rename", uuid4(), uuid4()),
            )
        )
        authority = AuthorityFixture(ContextUnavailable(403))
        handler = requests(channel, authority, journal)
        session = PanelEventSession(authority, channel, handler.emitter, journal, handler, None)
        await asyncio.wait_for(session.run(initial), 1)
        self.assertEqual(channel.closed, [4403])
        self.assertEqual([delivery.sequence for delivery in channel.deliveries], [1, 2])

    async def test_history_result_is_withheld_if_current_actor_changed_during_read(self) -> None:
        channel, journal = ChannelFixture(), JournalFixture()
        handler = requests(channel, AuthorityFixture(context()), journal)
        await handler.history(
            RpcRequest(
                "history", "events.history", HistorySelection(("mcp.calls",), None, 100, None)
            ),
            context(),
        )
        self.assertEqual(channel.replies[0].outcome, RpcFault("JOURNAL_UNAVAILABLE"))

    async def test_module_limit_returns_truthful_busy_without_running_ninth_request(self) -> None:
        channel, journal = ChannelFixture(), JournalFixture()
        handler = requests(channel, AuthorityFixture(context()), journal)
        for index in range(9):
            await handler.module(
                RpcRequest(str(index), "files.resources", ModuleRequest(uuid4(), None))
            )
        self.assertEqual(len(handler.modules), 8)
        self.assertEqual(channel.replies[0].identifier, "8")
        self.assertEqual(
            channel.replies[0].outcome, RpcFault("MODULE_REQUESTS_BUSY", uncertain=False)
        )
        tasks = tuple(handler.modules)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class ProtocolTests(unittest.TestCase):
    def test_rpc_rate_and_exact_envelope_fail_closed(self) -> None:
        frame = '{"jsonrpc":"2.0","id":"ping","method":"system.ping","params":{}}'
        with self.assertRaises(ValueError):
            request_frame(frame, messages=21)
        with self.assertRaises(ValueError):
            request_frame(frame.replace('"params":{}', '"params":{},"extra":true'), messages=1)

    def test_history_does_not_accept_boolean_limit_and_subscriptions_reject_unknown_topic(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            history({"limit": True})
        with self.assertRaises(ValueError):
            subscription({"topics": ["unknown"]})
        self.assertEqual(
            subscription({"topics": [], "cursor": "123-0"}), TopicSelection((), "123-0")
        )
