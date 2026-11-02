"""Authenticate owner transport and decode exact named management response contracts."""

from datetime import datetime
from functools import partial

from fastapi import WebSocket
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._platform_unix_peer import UnixPlatformPeer
from control_panel_api.domain.event_scope import EventScope
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_management import (
    InvitationCapabilities,
    InvitationOutcome,
    InviterOutcome,
    ManagementCommand,
    ManagementDirectory,
    ManagementErrorBody,
    ManagementInventory,
    ManagementOutcome,
    ManagementOutput,
    ManagementReceipt,
)
from control_panel_api.domain.realtime_payloads import PlatformMutation
from runtime_peer.platform_management_wire import ManagementEnvelope

from ._constructor_bindings import _PeerBinding, _PublisherBinding
from .management_wire import operation_input


def management_receipt(action: str, status: int, body: object) -> ManagementReceipt:
    if status != 200:
        return ManagementReceipt(status, TypeAdapter(ManagementErrorBody).validate_python(body))
    result: ManagementOutput
    if action in {"inventory", "team.read"}:
        result = TypeAdapter(ManagementInventory).validate_python(body)
    elif action == "directory":
        result = TypeAdapter(ManagementDirectory).validate_python(body)
    elif action == "invitation.capabilities":
        result = TypeAdapter(InvitationCapabilities).validate_python(body)
    elif action == "invitation.issue":
        result = TypeAdapter(InvitationOutcome).validate_python(body)
    elif action == "inviter.set":
        result = TypeAdapter(InviterOutcome).validate_python(body)
    else:
        result = TypeAdapter(ManagementOutcome).validate_python(body)
    return ManagementReceipt(status, result)


class PlatformManagementOwner(_PeerBinding[UnixPlatformPeer]):
    async def execute(
        self, context: PanelContext, command: ManagementCommand, expires_at: datetime
    ) -> ManagementReceipt:
        return await self._peer.management(
            ManagementEnvelope(
                issuer=context.session.issuer,
                subject=context.session.subject,
                operation_uuid=command.operation_uuid,
                action=command.action,
                data=operation_input(command.operation),
            ),
            expires_at=expires_at,
            decode=partial(management_receipt, command.action),
        )


class PlatformRpcAuthority:
    def __init__(self, socket: WebSocket, current_context: CurrentPlatformContext) -> None:
        self._socket = socket
        self._context = current_context

    async def current(self) -> PanelContext | None:
        value = await self._context(self._socket)
        return None if isinstance(value, JSONResponse) else PanelContext(*value)


class PlatformManagementEvents(_PublisherBinding):
    async def committed(self, event: PlatformMutation) -> None:
        await self._publisher.emit(
            "management.events",
            event.action,
            event,
            visibility=EventScope("operator"),
        )
