"""TLS-only Node-to-Resources protobuf transport with automatic retries disabled."""

import logging
from pathlib import Path
from urllib.parse import urlsplit

import grpc

from node_protocol.journal import (
    MAX_REPLY_BYTES,
    MAX_REQUEST_BYTES,
    SignedJournalReply,
    SignedJournalRequest,
)
from node_protocol.journal_grpc import journal_call

from .journal_client import JournalUnavailable


class GrpcJournalRpc:
    def __init__(self, target: str, ca_file: Path) -> None:
        parsed = urlsplit("//" + target)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or "://" in target
            or any(character.isspace() for character in target)
        ):
            raise ValueError("Explicit Resources journal TLS host:port required")
        self._target = target
        self._credentials = grpc.ssl_channel_credentials(root_certificates=ca_file.read_bytes())
        self._channel: grpc.aio.Channel | None = None

    async def exchange(self, request: SignedJournalRequest) -> SignedJournalReply:
        if self._channel is None:
            self._channel = grpc.aio.secure_channel(
                self._target,
                self._credentials,
                options=(
                    ("grpc.enable_retries", 0),
                    ("grpc.max_receive_message_length", MAX_REPLY_BYTES),
                    ("grpc.max_send_message_length", MAX_REQUEST_BYTES),
                ),
            )
        try:
            return await journal_call(self._channel, request, timeout=3)
        except grpc.aio.AioRpcError as error:
            logging.getLogger(__name__).error(
                "Resources journal RPC failed code=%s", error.code().name
            )
            raise JournalUnavailable("Resources journal RPC unavailable") from error

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close(grace=1)
            self._channel = None
