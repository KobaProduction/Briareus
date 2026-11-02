"""Decode private owner pages before application delivery, preserving failure order."""

from datetime import datetime
from uuid import UUID

from control_panel_api.application.owner_event_relay import (
    OwnerCursorFailure,
    OwnerEventFailure,
    OwnerEventPage,
)
from control_panel_api.domain.owner_events import (
    EventContractGap,
    EventFeed,
    OwnerCursor,
    OwnerEvent,
)

from .owner_event_contracts import McpOwnerEventWire, OwnerEventWire

_ENVELOPE_KEYS = frozenset(OwnerEventWire.model_fields)


def decode_event(value: object, feed: EventFeed) -> OwnerEvent | EventContractGap:
    if not isinstance(value, dict):
        raise ValueError("Invalid owner event envelope")
    event_type = value.get("type")
    if not isinstance(event_type, str):
        raise ValueError("Invalid owner event string")
    mcp_call = feed.source == "access" and event_type.startswith("mcp.call.")
    expected = _ENVELOPE_KEYS | {"call"} if mcp_call else _ENVELOPE_KEYS
    if set(value) != expected:
        raise ValueError("Invalid owner event envelope")
    if feed.source != "platform" and value["project_id"] != str(feed.project):
        raise ValueError("Invalid owner event binding")
    # An unrecognized contract is a resync signal, never a partially parsed event.
    if not feed.accepts(event_type):
        return EventContractGap(feed.source)
    model = McpOwnerEventWire if mcp_call else OwnerEventWire
    return model.model_validate(value).domain()


def _item(value: object, feed: EventFeed) -> OwnerEvent | EventContractGap | OwnerEventFailure:
    try:
        return decode_event(value, feed)
    except (ValueError, TypeError, KeyError) as exc:
        return OwnerEventFailure(str(exc))


def _cursor(value: object) -> OwnerCursor | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("Invalid owner continuation")
    occurred_at, event_id = value
    if not isinstance(occurred_at, str) or not isinstance(event_id, str):
        raise ValueError("Invalid owner continuation")
    datetime.fromisoformat(occurred_at)
    return OwnerCursor(occurred_at, UUID(event_id))


def _continuation(value: object) -> OwnerCursor | OwnerCursorFailure | None:
    try:
        return _cursor(value)
    except (ValueError, TypeError) as exc:
        return OwnerCursorFailure(str(exc))


def decode_page(value: object, feed: EventFeed) -> OwnerEventPage:
    if not isinstance(value, dict):
        raise ValueError("Invalid owner event page")
    items, truncated = value.get("items"), value.get("truncated")
    if not isinstance(items, list) or len(items) > 128 or type(truncated) is not bool:
        raise ValueError("Invalid owner event page")
    return OwnerEventPage(
        tuple(_item(item, feed) for item in items), truncated, _continuation(value.get("next"))
    )
