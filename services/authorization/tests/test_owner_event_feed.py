"""Event resume windows preserve retention, visibility and authority expiry."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from authorization.application.owner_events import ReadOwnerEvents
from authorization.domain.owner_events import (
    EventCursor,
    EventReadActor,
    EventReaderExpired,
    EventWindow,
    InvalidEventWindow,
    OwnerEvent,
)
from authorization.presentation.owner_events import page_response


class EventRepository:
    def __init__(self, count: int = 0) -> None:
        now = datetime.now(UTC)
        self.events = tuple(
            OwnerEvent(
                uuid4(), "session.opened", now, uuid4(), uuid4(), str(uuid4()), str(uuid4()), None
            )
            for _ in range(count)
        )
        self.window: EventWindow | None = None

    async def read(self, actor: EventReadActor, window: EventWindow) -> tuple[OwnerEvent, ...]:
        _ = actor
        self.window = window
        return self.events


def actor() -> EventReadActor:
    return EventReadActor(
        uuid4(), uuid4(), ("use_resources",), datetime.now(UTC) + timedelta(seconds=20)
    )


class OwnerEventFeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlapping_page_advances_only_last_returned_cursor(self) -> None:
        repository = EventRepository(129)
        now = datetime.now(UTC)
        result = await ReadOwnerEvents(repository).execute(
            actor(), EventWindow(now - timedelta(hours=1), now, None)
        )
        self.assertEqual(len(result.items), 128)
        self.assertEqual(
            result.next_cursor,
            EventCursor(repository.events[127].occurred_at, repository.events[127].event_uuid),
        )

    async def test_retention_clamp_marks_page_truncated(self) -> None:
        repository = EventRepository()
        now = datetime.now(UTC)
        result = await ReadOwnerEvents(repository).execute(
            actor(), EventWindow(now - timedelta(days=2), now, None)
        )
        self.assertTrue(result.truncated)
        self.assertIsNotNone(repository.window)
        if repository.window is not None:
            self.assertGreaterEqual(repository.window.since, now - timedelta(hours=24))

    async def test_expired_actor_cannot_release_query_result(self) -> None:
        now = datetime.now(UTC)
        with self.assertRaises(EventReaderExpired):
            await ReadOwnerEvents(EventRepository(1)).execute(
                replace(actor(), expires_at=now - timedelta(seconds=1)),
                EventWindow(now - timedelta(hours=1), now, None),
            )

    async def test_cursor_outside_clamped_retention_is_rejected(self) -> None:
        now = datetime.now(UTC)
        with self.assertRaises(InvalidEventWindow):
            await ReadOwnerEvents(EventRepository()).execute(
                actor(),
                EventWindow(
                    now - timedelta(days=2),
                    now,
                    EventCursor(now - timedelta(days=2), uuid4()),
                ),
            )

    async def test_wire_omits_non_call_metadata_but_keeps_null_resume_cursor(self) -> None:
        now = datetime.now(UTC)
        result = await ReadOwnerEvents(EventRepository(1)).execute(
            actor(), EventWindow(now - timedelta(hours=1), now, None)
        )
        payload = page_response(result).model_dump(mode="json")
        self.assertIsNone(payload["next"])
        self.assertNotIn("call", payload["items"][0])


if __name__ == "__main__":
    unittest.main()
