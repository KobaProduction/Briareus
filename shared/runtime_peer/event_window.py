"""Bounded, overlapping read windows for committed owner signal projections.

Contains no database/credential access. Owners supply their own authorised
query; audit details, command bodies and encrypted outcomes are never projected.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID


@dataclass(frozen=True)
class EventWindow:
    since: datetime
    until: datetime
    after: tuple[datetime, UUID] | None
    truncated: bool

    @classmethod
    def parse(cls, command):
        if not isinstance(command, dict) or set(command) - {"since", "until", "after"}:
            raise ValueError("Exact event window required")
        now = datetime.now(UTC)
        since, until = (datetime.fromisoformat(command[key]) for key in ("since", "until"))
        if (since.tzinfo is None or until.tzinfo is None or since > until
            or until > now + timedelta(seconds=5)):
            raise ValueError("Invalid event window")
        floor = now - timedelta(hours=24)
        after = command.get("after")
        if after is not None:
            if not isinstance(after, list) or len(after) != 2:
                raise ValueError("Invalid event cursor")
            after = datetime.fromisoformat(after[0]), UUID(after[1])
            if after[0].tzinfo is None or not since <= after[0] <= until:
                raise ValueError("Invalid event cursor")
        return cls(max(since, floor), until, after, since < floor)

    def result(self, rows):
        last = rows[127] if len(rows) > 128 else None
        return {"truncated": self.truncated,
            "next": [last.created_at.isoformat(), str(last.id)] if last else None,
            "items": [{"event_id": str(row.id), "occurredAt": row.created_at.isoformat(),
                "type": row.action.removeprefix("panel."),
                "actor_id": str(row.actor_user_id) if row.actor_user_id else None,
                "project_id": str(row.project_id) if row.project_id else None,
                "entity_id": row.object_id, "operation_id": str(row.operation_uuid)} for row in rows[:128]]}
