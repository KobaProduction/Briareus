"""Journal cursor progress remains bounded across invisible rows and retention gaps."""

import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from control_panel_api.application.realtime_journal import RealtimeJournal
from control_panel_api.domain.platform_authority import PlatformProjectContext, ResolvedPlatformUser
from control_panel_api.domain.realtime_events import EventScope, RealtimeEvent, cursor_number
from control_panel_api.domain.realtime_payloads import PanelCall
from control_panel_api.infrastructure.realtime_codec import decode_event, encode_event


@dataclass
class JournalFixture:
    rows: tuple[RealtimeEvent, ...]

    async def earliest(self) -> str | None:
        return self.rows[0].cursor if self.rows else None

    async def latest(self) -> str | None:
        return self.rows[-1].cursor if self.rows else None

    async def newer(self, cursor: str, count: int) -> tuple[RealtimeEvent, ...]:
        return tuple(
            row
            for row in self.rows
            if row.cursor and cursor_number(row.cursor) > cursor_number(cursor)
        )[:count]

    async def older(self, before: str | None, count: int) -> tuple[RealtimeEvent, ...]:
        return tuple(
            row
            for row in reversed(self.rows)
            if before is None or (row.cursor and cursor_number(row.cursor) < cursor_number(before))
        )[:count]


def owner_proof(project: UUID) -> ResolvedPlatformUser:
    actor = uuid4()
    return ResolvedPlatformUser(
        "https://issuer/",
        "subject",
        actor,
        True,
        "user",
        datetime.now(UTC) + timedelta(seconds=25),
        (),
        (PlatformProjectContext(project, "user", actor, ("use_resources",)),),
    )


def fixture_rows(project: UUID, foreign: UUID) -> tuple[RealtimeEvent, ...]:
    rows: list[RealtimeEvent] = []
    for number in range(1, 252):
        current = project if number % 2 else foreign
        rows.append(
            RealtimeEvent(
                "mcp.calls",
                "call.completed",
                datetime(2026, 10, 20, tzinfo=UTC),
                PanelCall(uuid4(), current, "files", "file_list", uuid4(), "completed", 1),
                EventScope("project", id=current),
                event_id=str(number),
                cursor=f"{number}-0",
            )
        )
    return tuple(rows)


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cursor_continues_without_duplicates_or_foreign_output(self) -> None:
        project, foreign = uuid4(), uuid4()
        journal = RealtimeJournal(JournalFixture(fixture_rows(project, foreign)))
        proof = owner_proof(project)
        first = await journal.history(
            proof=proof,
            topics={"mcp.calls"},
            before=None,
            project=str(project),
            limit=100,
        )
        self.assertEqual(len(first.items), 100)
        self.assertTrue(first.has_more)
        second = await journal.history(
            proof=proof,
            topics={"mcp.calls"},
            before=first.next_cursor,
            project=str(project),
            limit=100,
        )
        self.assertEqual(len(second.items), 26)
        self.assertFalse(second.has_more)
        self.assertFalse({e.event_id for e in first.items} & {e.event_id for e in second.items})
        self.assertTrue(all(e.project_id == project for e in first.items + second.items))

    async def test_foreign_project_and_unavailable_broker_fail_closed(self) -> None:
        from control_panel_api._realtime_bus import PanelEvents

        project, foreign = uuid4(), uuid4()
        journal = RealtimeJournal(JournalFixture(fixture_rows(project, foreign)))
        with self.assertRaises(ValueError):
            await journal.history(
                proof=owner_proof(project),
                topics={"mcp.calls"},
                before=None,
                project=str(foreign),
                limit=100,
            )
        with self.assertRaises(ValueError):
            await PanelEvents().history(proof=owner_proof(project), topics={"mcp.calls"})

    async def test_expired_cursor_reports_retention_gap(self) -> None:
        project = uuid4()
        journal = RealtimeJournal(JournalFixture(fixture_rows(project, uuid4())[50:]))
        result = await journal.history(
            proof=owner_proof(project),
            topics={"mcp.calls"},
            before="1-0",
            project=None,
            limit=100,
        )
        self.assertTrue(result.retention_gap)
        self.assertFalse(result.has_more)

    async def test_codec_preserves_deployed_scope_fields_and_cursor(self) -> None:
        event = fixture_rows(uuid4(), uuid4())[0]
        self.assertEqual(decode_event(encode_event(event)), event)
