"""Valkey stream codec; journal application receives typed ordered events."""

from dataclasses import replace

from valkey.asyncio import Valkey
from valkey.exceptions import ValkeyError

from control_panel_api.application.realtime_journal import JournalUnavailable
from control_panel_api.domain.realtime_events import RealtimeEvent

from .realtime_codec import decode_event

JOURNAL = "briareus:panel:events:journal"


def _row_cursor(row: object) -> str:
    if not isinstance(row, (tuple, list)) or len(row) != 2 or not isinstance(row[0], str):
        raise ValueError("Invalid Valkey journal row")
    return row[0]


def _journal_event(row: object) -> RealtimeEvent:
    cursor = _row_cursor(row)
    if not isinstance(row, (tuple, list)) or not isinstance(row[1], dict):
        raise ValueError("Invalid Valkey journal event")
    raw = row[1].get("event")
    if not isinstance(raw, str):
        raise ValueError("Invalid Valkey journal envelope")
    return replace(decode_event(raw), cursor=cursor)


class ValkeyEventJournal:
    def __init__(self, client: Valkey | None = None) -> None:
        self.client = client

    def _available(self) -> Valkey:
        if self.client is None:
            raise JournalUnavailable("JOURNAL_UNAVAILABLE")
        return self.client

    async def earliest(self) -> str | None:
        try:
            rows = await self._available().xrange(JOURNAL, count=1)
        except ValkeyError:
            raise JournalUnavailable("JOURNAL_UNAVAILABLE") from None
        return _row_cursor(rows[0]) if rows else None

    async def latest(self) -> str | None:
        try:
            rows = await self._available().xrevrange(JOURNAL, count=1)
        except ValkeyError:
            raise JournalUnavailable("JOURNAL_UNAVAILABLE") from None
        return _row_cursor(rows[0]) if rows else None

    async def newer(self, cursor: str, count: int) -> tuple[RealtimeEvent, ...]:
        try:
            rows = await self._available().xrange(JOURNAL, min="(" + cursor, max="+", count=count)
        except ValkeyError:
            raise JournalUnavailable("JOURNAL_UNAVAILABLE") from None
        return tuple(
            replace(decode_event(fields["event"]), cursor=cursor) for cursor, fields in rows
        )

    async def older(self, before: str | None, count: int) -> tuple[RealtimeEvent, ...]:
        try:
            rows = await self._available().xrevrange(
                JOURNAL,
                max="(" + before if before else "+",
                count=count,
            )
        except ValkeyError:
            raise JournalUnavailable("JOURNAL_UNAVAILABLE") from None
        return tuple(
            replace(decode_event(fields["event"]), cursor=cursor) for cursor, fields in rows
        )
