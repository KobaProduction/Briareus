"""Existing JSON-RPC output frames with concrete event, result and error schemas."""

from collections.abc import Callable
from functools import partial
from operator import is_
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from control_panel_api.application.panel_channel import RpcPayload
from control_panel_api.application.platform_projection import PlatformContextPayload
from control_panel_api.infrastructure.module_replies import NativeToolReply
from control_panel_api.infrastructure.realtime_codec import EventEnvelope, HistoryEnvelope


class Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityStatus(Frame):
    authenticated: Literal[True]
    authority: Literal["rauthy"]
    issuer: str
    subject: str
    client_id: str
    expires_at: str
    platform_membership_verified: Literal[False] = False
    permissions: tuple[str, ...] = ()


class ContextData(Frame):
    context: PlatformContextPayload
    identity: IdentityStatus


class StreamPosition(Frame):
    stream_id: str
    sequence: int


class ContextEvent(Frame):
    topic: Literal["platform.context"]
    type: Literal["snapshot"]
    occurredAt: str
    data: ContextData


class ContextDelivery(ContextEvent, StreamPosition):
    """Context projection augmented with the connection's delivery position."""


class ControlDelivery(StreamPosition):
    type: Literal["session.refresh", "source.unavailable"]


class JournalDelivery(EventEnvelope):
    stream_id: str
    sequence: int


class EventFrame(Frame):
    jsonrpc: Literal["2.0"]
    method: Literal["events.deliver"]
    params: JournalDelivery | ControlDelivery | ContextDelivery


class UncertainOperation(Frame):
    uncertain: bool


_absent: Callable[[object], bool] = partial(is_, None)


class RpcError(Frame):
    code: int
    message: str
    data: UncertainOperation | None = Field(default=None, exclude_if=_absent)


class ErrorFrame(Frame):
    jsonrpc: Literal["2.0"]
    id: str
    error: RpcError


class ResultFrame(Frame):
    jsonrpc: Literal["2.0"]
    id: str
    result: RpcPayload[NativeToolReply] | HistoryEnvelope


type OutboundFrame = EventFrame | ErrorFrame | ResultFrame
