"""Purpose-bound gRPC journal ingress; existing private owner HTTP is unchanged."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import grpc
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from common.platform_db import PlatformDatabase
from node_protocol.journal import (
    MAX_REPLY_BYTES,
    MAX_REQUEST_BYTES,
    JournalResult,
    SignedJournalReply,
    SignedJournalRequest,
    sign_reply,
)
from projects.infrastructure.node_journal import (
    JournalConflict,
    JournalRejected,
    JournalUnavailable,
    SqlNodeJournal,
)


class JournalService(Protocol):
    async def execute(self, envelope: SignedJournalRequest, *, now: int) -> JournalResult: ...


class JournalServiceProvider:
    """Use the running Resources database; never construct a second owner pool."""

    def __init__(
        self,
        signing_key: Ed25519PrivateKey,
        gateway_key: Ed25519PublicKey | None,
    ) -> None:
        self.signing_key = signing_key
        self.gateway_key = gateway_key
        self._database: Callable[[], PlatformDatabase | None] | None = None
        self._server: grpc.aio.Server | None = None

    def bind_database(self, resolver: Callable[[], PlatformDatabase | None]) -> None:
        self._database = resolver

    def resolve(self) -> JournalService | None:
        database = self._database() if self._database is not None else None
        if database is None:
            return None
        return SqlNodeJournal(database, self.signing_key.public_key(), self.gateway_key)

    async def execute(self, envelope: SignedJournalRequest) -> SignedJournalReply:
        result, status = await self._execute(envelope)
        signed = sign_reply(
            envelope.request, result, self.signing_key, status_code=status, now=int(time.time())
        )
        if len(signed.model_dump_json().encode()) > MAX_REPLY_BYTES:
            return sign_reply(
                envelope.request,
                JournalResult(error="JOURNAL_UNAVAILABLE"),
                self.signing_key,
                status_code=503,
                now=int(time.time()),
            )
        return signed

    async def _execute(self, envelope: SignedJournalRequest) -> tuple[JournalResult, int]:
        try:
            service = self.resolve()
            if service is None:
                raise JournalUnavailable("Journal owner unavailable")
            async with asyncio.timeout(8):
                result = await service.execute(envelope, now=int(time.time()))
            return result, 200
        except JournalRejected:
            return JournalResult(error="JOURNAL_REJECTED"), 403
        except JournalConflict:
            return JournalResult(error="JOURNAL_CONFLICT"), 409
        except Exception:
            # No database diagnostics, key material or signed inputs cross RPC.
            return JournalResult(error="JOURNAL_UNAVAILABLE"), 503

    async def start(self) -> None:
        """Start only an explicitly configured, TLS-only private listener."""
        bind = os.environ.get("RESOURCES_NODE_JOURNAL_BIND")
        certificate = os.environ.get("RESOURCES_NODE_JOURNAL_TLS_CERT_FILE")
        private_key = os.environ.get("RESOURCES_NODE_JOURNAL_TLS_KEY_FILE")
        if not any((bind, certificate, private_key)):
            # Existing owner-only deployments remain usable; Node fails closed
            # until its required journal endpoint and pin are configured.
            return
        if not bind or not certificate or not private_key:
            raise ValueError("Complete Resources journal gRPC TLS configuration required")
        from node_protocol.journal_grpc import register_journal

        server = grpc.aio.server(
            options=(
                ("grpc.max_receive_message_length", MAX_REQUEST_BYTES),
                ("grpc.max_send_message_length", MAX_REPLY_BYTES),
                ("grpc.so_reuseport", 0),
            )
        )
        register_journal(server, self.execute)
        credentials = await asyncio.to_thread(_tls_credentials, private_key, certificate)
        try:
            if not server.add_secure_port(bind, credentials):
                raise ValueError("Resources journal listener unavailable")
            await server.start()
        except BaseException:
            await server.stop(0)
            raise
        self._server = server

    async def close(self) -> None:
        if self._server is not None:
            await self._server.stop(3)
            self._server = None


def _tls_credentials(private_key: str, certificate: str) -> grpc.ServerCredentials:
    return grpc.ssl_server_credentials(
        [(Path(private_key).read_bytes(), Path(certificate).read_bytes())]
    )
