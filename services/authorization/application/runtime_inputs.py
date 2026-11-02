"""Concrete commands for the existing private human runtime protocol."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from authorization.application.access_inputs import (
    ApprovalListCommand,
    OpenSessionCommand,
    RequestElevationCommand,
    ResolveElevationCommand,
    RevokeSessionCommand,
    SessionGetCommand,
)
from authorization.application.runtime_effects import RuntimeEffectCall as RuntimeEffectCall
from authorization.domain.owner_events import EventCursor, EventWindow
from runtime_peer.access_management_wire import RuntimeResourceInput as RuntimeResourceQuery
from runtime_peer.event_window_wire import EventWindowFields

__all__ = (
    "COMMAND_TYPES",
    "RuntimeAction",
    "RuntimeCommand",
    "RuntimeEffectCall",
    "RuntimeEventQuery",
    "RuntimeInput",
    "RuntimeResourceQuery",
    "RuntimeWriteCommand",
)

type RuntimeAction = Literal[
    "session.open",
    "session.revoke",
    "session.list",
    "session.get",
    "approval.list",
    "events.read",
    "session.request_elevation",
    "session.resolve_elevation",
    "terminal.prepare",
    "files.prepare",
    "web.prepare",
    "resource.list",
]


class RuntimeEventQuery(EventWindowFields):
    def window(self) -> EventWindow:
        cursor = (
            None
            if self.after is None
            else EventCursor(datetime.fromisoformat(self.after[0]), UUID(self.after[1]))
        )
        return EventWindow(
            datetime.fromisoformat(self.since), datetime.fromisoformat(self.until), cursor
        )


type RuntimeWriteCommand = (
    OpenSessionCommand | RequestElevationCommand | ResolveElevationCommand | RevokeSessionCommand
)
type RuntimeInput = (
    RuntimeWriteCommand
    | ApprovalListCommand
    | SessionGetCommand
    | RuntimeEventQuery
    | RuntimeResourceQuery
)
type RuntimeCommand = RuntimeInput | RuntimeEffectCall

COMMAND_TYPES: dict[str, type[RuntimeInput]] = {
    "session.open": OpenSessionCommand,
    "session.revoke": RevokeSessionCommand,
    "session.request_elevation": RequestElevationCommand,
    "session.resolve_elevation": ResolveElevationCommand,
    "session.list": ApprovalListCommand,
    "session.get": SessionGetCommand,
    "approval.list": ApprovalListCommand,
    "events.read": RuntimeEventQuery,
    "resource.list": RuntimeResourceQuery,
}
