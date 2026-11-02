"""WebSocket frame serialization for the application channel ports."""

from dataclasses import dataclass

from fastapi import WebSocket, WebSocketDisconnect
from mcp_types import CallToolResult

from control_panel_api.application.panel_channel import (
    ChannelDisconnected,
    ContextSnapshot,
    ControlNotice,
    EventDelivery,
    PanelEvent,
    RpcFault,
    RpcPayload,
    RpcReply,
)
from control_panel_api.application.platform_projection import platform_context_payload
from control_panel_api.domain.realtime_events import EventHistory
from control_panel_api.infrastructure.module_replies import NativeToolReply
from control_panel_api.infrastructure.realtime_codec import (
    HistoryEnvelope,
    event_envelope,
    history_envelope,
)

from .panel_frames import (
    ContextData,
    ContextDelivery,
    ContextEvent,
    ControlDelivery,
    ErrorFrame,
    EventFrame,
    IdentityStatus,
    JournalDelivery,
    OutboundFrame,
    ResultFrame,
    RpcError,
    UncertainOperation,
)


def context_event(snapshot: ContextSnapshot) -> ContextEvent:
    session, proof = snapshot.context.session, snapshot.context.proof
    return ContextEvent(
        topic="platform.context",
        type="snapshot",
        occurredAt=snapshot.occurred_at.isoformat(),
        data=ContextData(
            context=platform_context_payload(session, proof),
            identity=IdentityStatus(
                authenticated=True,
                authority="rauthy",
                issuer=session.issuer,
                subject=session.subject,
                client_id=session.client_id,
                expires_at=session.expires_at.isoformat(),
                platform_membership_verified=False,
                permissions=(),
            ),
        ),
    )


def _delivery_params(
    delivery: EventDelivery,
) -> JournalDelivery | ControlDelivery | ContextDelivery:
    notice = delivery.notice
    if isinstance(notice, PanelEvent):
        event = event_envelope(notice)
        return JournalDelivery(
            topic=event.topic,
            type=event.type,
            occurredAt=event.occurredAt,
            data=event.data,
            scope=event.scope,
            event_id=event.event_id,
            version=event.version,
            cursor=event.cursor,
            stream_id=delivery.stream_id,
            sequence=delivery.sequence,
        )
    if isinstance(notice, ControlNotice):
        return ControlDelivery(
            type=notice.type, stream_id=delivery.stream_id, sequence=delivery.sequence
        )
    context = context_event(notice)
    return ContextDelivery(
        topic=context.topic,
        type=context.type,
        occurredAt=context.occurredAt,
        data=context.data,
        stream_id=delivery.stream_id,
        sequence=delivery.sequence,
    )


def _reply_frame(reply: RpcReply[NativeToolReply]) -> ErrorFrame | ResultFrame:
    outcome = reply.outcome
    if isinstance(outcome, RpcFault):
        uncertain = (
            None if outcome.uncertain is None else UncertainOperation(uncertain=outcome.uncertain)
        )
        return ErrorFrame(
            jsonrpc="2.0",
            id=reply.identifier,
            error=RpcError(code=outcome.code, message=outcome.message, data=uncertain),
        )
    value: RpcPayload[NativeToolReply] | HistoryEnvelope = outcome.value
    if isinstance(value, EventHistory):
        value = history_envelope(value)
    return ResultFrame(jsonrpc="2.0", id=reply.identifier, result=value)


@dataclass(frozen=True, slots=True)
class PanelSocket:
    socket: WebSocket

    async def receive(self) -> str:
        try:
            return await self.socket.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            raise ChannelDisconnected from None

    async def event(self, delivery: EventDelivery) -> None:
        await self.send(
            EventFrame(jsonrpc="2.0", method="events.deliver", params=_delivery_params(delivery))
        )

    async def reply(self, reply: RpcReply[NativeToolReply]) -> None:
        await self.send(_reply_frame(reply))

    async def send(self, message: OutboundFrame) -> None:
        try:
            await self.socket.send_text(
                message.model_dump_json(
                    exclude_unset=True,
                    by_alias=isinstance(message, ResultFrame)
                    and isinstance(message.result, CallToolResult),
                )
            )
        except (WebSocketDisconnect, RuntimeError):
            raise ChannelDisconnected from None

    async def close(self, code: int) -> None:
        await self.socket.close(code=code)
