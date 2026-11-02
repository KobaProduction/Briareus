"""Typed unary gRPC boundary for the signed Node/Resources execution journal."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import grpc

from . import journal_pb2 as pb
from .journal import SignedJournalReply, SignedJournalRequest
from .journal_codec import decode_reply as decode_reply
from .journal_codec import decode_request as decode_request
from .journal_codec import encode_reply as encode_reply
from .journal_codec import encode_request as encode_request

SERVICE = "briareus.node.journal.ExecutionJournal"
METHOD = "/" + SERVICE + "/Exchange"
type JournalHandler = Callable[[SignedJournalRequest], Awaitable[SignedJournalReply]]
type JournalContext = grpc.aio.ServicerContext[pb.SignedJournalRequest, pb.SignedJournalReply]


async def journal_call(
    channel: grpc.aio.Channel,
    envelope: SignedJournalRequest,
    *,
    timeout: float = 3,  # noqa: ASYNC109 -- gRPC must receive the transport deadline for cancellation
) -> SignedJournalReply:
    if not 0 < timeout <= 3:
        raise ValueError("Bounded journal RPC deadline required")
    call: grpc.aio.UnaryUnaryMultiCallable[pb.SignedJournalRequest, pb.SignedJournalReply] = (
        channel.unary_unary(
            METHOD,
            request_serializer=pb.SignedJournalRequest.SerializeToString,
            response_deserializer=pb.SignedJournalReply.FromString,
        )
    )
    response = await call(encode_request(envelope), timeout=timeout)
    return decode_reply(response)


class JournalService:
    def __init__(self, handler: JournalHandler) -> None:
        self.handler = handler

    async def exchange(
        self, request: pb.SignedJournalRequest, context: JournalContext
    ) -> pb.SignedJournalReply:
        if any(
            key.lower() in {"cookie", "origin", "authorization"}
            for key, _value in context.invocation_metadata()
        ):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Private journal peer required")
        try:
            envelope = decode_request(request)
        except (ValueError, TypeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Journal request rejected")
            raise
        try:
            remaining = min(3, envelope.request.expires_at - time.time())
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                reply = await self.handler(envelope)
            return encode_reply(reply)
        except TimeoutError:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Journal request expired")
            raise
        except grpc.RpcError:
            raise
        except Exception:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Journal unavailable")
            raise


def register_journal(server: grpc.aio.Server, handler: JournalHandler) -> None:
    service = JournalService(handler)
    method = grpc.unary_unary_rpc_method_handler(
        service.exchange,
        request_deserializer=pb.SignedJournalRequest.FromString,
        response_serializer=pb.SignedJournalReply.SerializeToString,
    )
    server.add_generic_rpc_handlers(
        (grpc.method_handlers_generic_handler(SERVICE, {"Exchange": method}),)
    )
