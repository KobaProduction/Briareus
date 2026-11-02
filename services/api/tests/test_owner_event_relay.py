"""Owner relay progress is ordered, scoped and committed only after a complete page."""

import unittest
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from control_panel_api.application.owner_event_relay import (
    OwnerEventPage,
    OwnerEventRelay,
    RelayNotice,
)
from control_panel_api.domain.owner_events import (
    EventAuthority,
    EventFeed,
    EventProject,
    EventWindow,
    OwnerCursor,
    OwnerEvent,
    published_event_id,
    visibility_for,
)
from control_panel_api.infrastructure.owner_event_contracts import OwnerEventWire
from control_panel_api.infrastructure.owner_event_decoder import (
    decode_event,
    decode_page,
)


def wire(item: OwnerEvent) -> OwnerEventWire:
    return OwnerEventWire.model_validate(asdict(item))


@dataclass
class JournalFixture:
    page: OwnerEventPage

    async def read(self, feed: EventFeed, window: EventWindow) -> OwnerEventPage:
        assert feed.source == "access"
        assert window.until >= window.since
        return self.page


@dataclass
class SinkFixture:
    published: list[OwnerEvent] = field(default_factory=list)

    async def publish(self, event: OwnerEvent, feed: EventFeed, authority: EventAuthority) -> None:
        assert feed.source == "access"
        assert authority.expires_at.tzinfo is not None
        self.published.append(event)


def authority(project: UUID) -> EventAuthority:
    return EventAuthority(
        uuid4(),
        True,
        datetime.now(UTC) + timedelta(seconds=30),
        (EventProject(project, True, True),),
    )


def event(project: UUID) -> OwnerEvent:
    return OwnerEvent(
        uuid4(),
        "session.opened",
        datetime.now(UTC).isoformat(),
        uuid4(),
        project,
        uuid4(),
        uuid4(),
    )


async def notices(
    relay: OwnerEventRelay,
    proof: EventAuthority,
    journal: JournalFixture,
    sink: SinkFixture,
) -> tuple[RelayNotice, ...]:
    return tuple(
        [
            item
            async for item in relay.read(
                proof,
                available=frozenset({"access"}),
                journal=journal,
                sink=sink,
            )
        ]
    )


class OwnerRelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_later_event_preserves_prior_delivery_without_advancing_cursor(
        self,
    ) -> None:
        project = uuid4()
        relay, sink = OwnerEventRelay(), SinkFixture()
        first = event(project)
        journal = JournalFixture(
            decode_page(
                {
                    "items": [wire(first).model_dump(mode="json"), {"type": "broken"}],
                    "truncated": False,
                    "next": None,
                },
                EventFeed("access", project),
            )
        )
        result = await notices(relay, authority(project), journal, sink)
        self.assertEqual(sink.published, [first])
        self.assertEqual(result[0].type, "source.unavailable")
        self.assertNotIn(("access", str(project)), relay.windows)
        self.assertFalse(relay.health[("access", str(project))])

    async def test_bad_continuation_is_checked_after_delivery_and_recovery_is_once(self) -> None:
        project = uuid4()
        relay, sink = OwnerEventRelay(), SinkFixture()
        first, proof = event(project), authority(project)
        journal = JournalFixture(
            decode_page(
                {
                    "items": [wire(first).model_dump(mode="json")],
                    "truncated": False,
                    "next": ["invalid", "invalid"],
                },
                EventFeed("access", project),
            )
        )
        initial = await notices(relay, proof, journal, sink)
        self.assertEqual(initial[0].type, "source.unavailable")
        self.assertEqual(sink.published, [first])
        self.assertFalse(await notices(relay, proof, journal, sink))
        journal.page = OwnerEventPage((), False, None)
        recovered = await notices(relay, proof, journal, sink)
        self.assertEqual(recovered[0].type, "source.recovered")
        self.assertFalse(await notices(relay, proof, journal, sink))

    async def test_future_event_is_opaque_resync_and_does_not_block_current_events(self) -> None:
        project = uuid4()
        relay, sink = OwnerEventRelay(), SinkFixture()
        current = event(project)
        future = {
            **wire(current).model_dump(mode="json"),
            "type": "future.event",
            "entity_id": "future-selector",
        }
        cursor = [datetime.now(UTC).isoformat(), str(uuid4())]
        journal = JournalFixture(
            decode_page(
                {
                    "items": [future, wire(current).model_dump(mode="json")],
                    "truncated": True,
                    "next": cursor,
                },
                EventFeed("access", project),
            )
        )
        result = await notices(relay, authority(project), journal, sink)
        self.assertEqual(
            [item.type for item in result],
            ["resync.required", "resync.required", "source.connected"],
        )
        self.assertEqual(sink.published, [current])
        self.assertEqual(
            relay.windows[("access", str(project))].after, OwnerCursor(cursor[0], UUID(cursor[1]))
        )

    async def test_expired_proof_stops_owner_reads(self) -> None:
        project = uuid4()
        expired = EventAuthority(
            uuid4(),
            True,
            datetime.now(UTC) - timedelta(seconds=1),
            (EventProject(project, True, True),),
        )
        relay, sink = OwnerEventRelay(), SinkFixture()
        result = await notices(
            relay, expired, JournalFixture(OwnerEventPage((), False, None)), sink
        )
        self.assertFalse(result)
        self.assertFalse(relay.windows)
        self.assertFalse(relay.health)


class HumanBrowserEventTests(unittest.TestCase):
    def test_human_web_call_preserves_actor_without_an_agent_session(self) -> None:
        from control_panel_api.domain.owner_events import McpCall, McpOwnerEvent
        from control_panel_api.infrastructure.owner_event_contracts import McpOwnerEventWire

        project, actor, placement = uuid4(), uuid4(), uuid4()
        original = McpOwnerEvent(
            uuid4(),
            "mcp.call.completed",
            datetime.now(UTC).isoformat(),
            actor,
            project,
            uuid4(),
            placement,
            McpCall("web", "local_browser_open", "completed", None, uuid4(), placement, 12),
        )
        wire = McpOwnerEventWire.model_validate(asdict(original)).model_dump(mode="json")
        decoded = decode_event(wire, EventFeed("access", project))
        self.assertEqual(decoded, original)
        self.assertIsInstance(decoded, McpOwnerEvent)
        self.assertIsNone(original.call.session_uuid)
        self.assertEqual(original.actor_id, actor)


class EventPolicyTests(unittest.TestCase):
    def test_rotation_is_bounded_and_reaches_large_memberships(self) -> None:
        projects = tuple(EventProject(uuid4(), True, True) for _ in range(9))
        proof = EventAuthority(uuid4(), True, datetime.now(UTC), projects)
        relay = OwnerEventRelay()
        seen: set[UUID | None] = set()
        for _ in range(3):
            feeds = relay.feeds(proof, frozenset({"access"}))
            self.assertEqual(len(feeds), 4)
            seen.update(feed.project for feed in feeds)
        self.assertEqual(seen, {project.project_uuid for project in projects})

    def test_platform_events_are_actor_scoped_and_deduplicated_per_actor(self) -> None:
        project, actor = uuid4(), uuid4()
        proof = EventAuthority(actor, False, datetime.now(UTC), ())
        item, feed = event(project), EventFeed("platform")
        scope = visibility_for(feed, item, proof)
        self.assertEqual((scope.kind, scope.id), ("actor", actor))
        self.assertEqual(
            published_event_id(feed, item, proof),
            "platform:" + str(item.event_id) + ":" + str(actor),
        )

    def test_foreign_project_and_non_boolean_truncation_fail_closed(self) -> None:
        project = uuid4()
        with self.assertRaises(ValueError):
            decode_event(wire(event(project)).model_dump(mode="json"), EventFeed("access", uuid4()))
        with self.assertRaises(ValueError):
            decode_page({"items": [], "truncated": 1}, EventFeed("access", project))
