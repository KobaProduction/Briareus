"""Bounded event policies and the committed public projection contract."""

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import JsonValue

from runtime_peer.event_window import EventWindow
from runtime_peer.event_window_wire import EventWindowRequest

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
EVENT_UUID = UUID("00000000-0000-4000-8000-000000000001")


def test_pure_policy_imports_without_site_packages() -> None:
    result = subprocess.run(  # noqa: S603 -- fixed interpreter/argv and code; no user source input
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from runtime_peer.event_window import EventWindow; "
            "assert 'runtime_peer.transport' not in sys.modules; assert 'jwt' not in sys.modules",
            str(Path(__file__).resolve().parents[1]),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@dataclass(frozen=True)
class CommittedEvent:
    id: UUID
    created_at: datetime
    action: str = "panel.project.updated"
    actor_user_id: UUID | None = None
    project_id: UUID | None = None
    object_id: str = "project-example"
    operation_uuid: UUID = EVENT_UUID
    details: str = "private audit details"


def test_window_clips_retention_and_preserves_original_cursor() -> None:
    since = NOW - timedelta(days=2)
    cursor_time = since + timedelta(hours=1)
    request = EventWindowRequest(
        since=since.isoformat(),
        until=NOW.isoformat(),
        after=(cursor_time.isoformat(), str(EVENT_UUID)),
    )
    window = request.window(now=NOW)
    assert window.since == NOW - timedelta(hours=24)
    assert window.until == NOW
    assert window.after == (cursor_time, EVENT_UUID)
    assert window.truncated


@pytest.mark.parametrize("count", [0, 127, 128, 129])
def test_page_cursor_marks_last_emitted_row_only_when_more_exist(count: int) -> None:
    request = EventWindowRequest(
        since=(NOW - timedelta(hours=1)).isoformat(), until=NOW.isoformat()
    )
    window = request.window(now=NOW)
    rows = [CommittedEvent(UUID(int=index + 1), NOW) for index in range(count)]
    page = window.result(rows)
    assert len(page.items) == min(count, 128)
    assert page.next == ((NOW.isoformat(), str(rows[127].id)) if count > 128 else None)
    assert not page.truncated


def test_public_projection_preserves_wire_fields_and_excludes_audit_details() -> None:
    window = EventWindow(NOW, NOW, None, False)
    row = CommittedEvent(EVENT_UUID, NOW, actor_user_id=EVENT_UUID, project_id=EVENT_UUID)
    encoded = json.loads(json.dumps(asdict(window.result([row]))))
    assert encoded == {
        "truncated": False,
        "next": None,
        "items": [
            {
                "event_id": str(EVENT_UUID),
                "occurredAt": NOW.isoformat(),
                "type": "project.updated",
                "actor_id": str(EVENT_UUID),
                "project_id": str(EVENT_UUID),
                "entity_id": "project-example",
                "operation_id": str(EVENT_UUID),
            }
        ],
    }


@pytest.mark.parametrize(
    "command",
    [
        None,
        {},
        {"since": 1, "until": "bad"},
        {"since": "2026-10-21T12:00:00", "until": NOW.isoformat()},
        {"since": NOW.isoformat(), "until": (NOW + timedelta(seconds=6)).isoformat()},
        {"since": NOW.isoformat(), "until": (NOW - timedelta(seconds=1)).isoformat()},
        {"since": NOW.isoformat(), "until": NOW.isoformat(), "unexpected": True},
        {"since": NOW.isoformat(), "until": NOW.isoformat(), "after": []},
        {"since": NOW.isoformat(), "until": NOW.isoformat(), "after": [NOW.isoformat(), 1]},
        {
            "since": NOW.isoformat(),
            "until": NOW.isoformat(),
            "after": [(NOW - timedelta(seconds=1)).isoformat(), str(EVENT_UUID)],
        },
    ],
)
def test_invalid_windows_fail_closed(command: JsonValue) -> None:
    with pytest.raises(ValueError):
        EventWindowRequest.model_validate(command).window(now=NOW)
