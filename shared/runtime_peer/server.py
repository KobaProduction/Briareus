"""Private owner listener: OS peer identity plus operation-bound signatures."""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import jwt
import uvicorn
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.protocols.http.h11_impl import H11Protocol

from .transport import (
    _LIFETIME,
    _MAX_BODY,
    _MAX_RESPONSE,
    _TYPE,
    PeerRejected,
    PeerVerifier,
    VerifiedServiceRequest,
    _private_key,
)


class UnixPeerProtocol(H11Protocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        if not isinstance(transport, asyncio.Transport):
            raise TypeError("An HTTP stream transport is required")
        super().connection_made(transport)
        connection = transport.get_extra_info("socket")
        uid = None
        if connection is not None and connection.family == socket.AF_UNIX:
            _, uid, _ = struct.unpack(
                "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
        application = self.app

        async def with_peer(scope: Scope, receive: Receive, send: Send) -> None:
            await application({**scope, "briareus.unix_peer_uid": uid}, receive, send)

        self.app = with_peer


@dataclass(frozen=True, slots=True)
class _OwnerRequest:
    proof: VerifiedServiceRequest
    body: bytes


async def _read_body(receive: Receive) -> bytes:
    body = bytearray()
    async with asyncio.timeout(3):
        while True:
            message = await receive()
            if message["type"] != "http.request":
                raise PeerRejected("Request disconnected")
            body.extend(message.get("body", b""))
            if len(body) > _MAX_BODY:
                raise PeerRejected("Request too large")
            if not message.get("more_body", False):
                return bytes(body)


def _request_token(scope: Scope) -> str:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    authorization = [value for key, value in headers if key == b"authorization"]
    if (
        len(authorization) != 1
        or not authorization[0].startswith(b"Bearer ")
        or any(key in {b"cookie", b"origin"} for key, _ in headers)
        or scope.get("query_string")
        or scope.get("method") != "POST"
        or scope.get("raw_path") != scope["path"].encode("ascii")
        or not scope["path"].startswith("/internal/v1/")
    ):
        raise PeerRejected("Private RPC envelope required")
    return authorization[0][7:].decode("ascii")


class SignedOwnerApp:
    """No TCP/header fallback. The application receives only authenticated RPC."""

    def __init__(self, app: ASGIApp, *, verifier: PeerVerifier, signing_key_file: str) -> None:
        self.app, self.verifier = app, verifier
        self.key = _private_key(signing_key_file)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        if (
            scope.get("method") in {"GET", "HEAD"}
            and scope.get("path") in {"/health/live", "/health/ready"}
            and not scope.get("query_string")
        ):
            await self.app(scope, receive, send)
            return
        try:
            request = await self._authenticate(scope, receive)
        except (PeerRejected, TimeoutError, UnicodeError, KeyError, ValueError):
            await JSONResponse({"error": {"code": "SERVICE_PEER_REQUIRED"}}, status_code=401)(
                scope, receive, send
            )
            return
        response = await self._invoke(scope, request)
        self._sign_response(response, request.proof)
        for message in response:
            await send(message)

    async def _authenticate(self, scope: Scope, receive: Receive) -> _OwnerRequest:
        body = await _read_body(receive)
        proof = self.verifier.verify_request(
            token=_request_token(scope),
            uid=scope.get("briareus.unix_peer_uid"),
            method=scope["method"],
            path=scope["path"],
            body=body,
        )
        return _OwnerRequest(proof=proof, body=body)

    async def _invoke(self, scope: Scope, request: _OwnerRequest) -> list[Message]:
        delivered = False

        async def original_body() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": request.body, "more_body": False}

        response: list[Message] = []
        size = 0

        async def capture(message: Message) -> None:
            nonlocal size
            if message["type"] == "http.response.body":
                size += len(message.get("body", b""))
                if size > _MAX_RESPONSE:
                    raise PeerRejected("Owner output too large")
            response.append(message)

        await self.app(
            {**scope, "briareus.service_peer": request.proof.caller}, original_body, capture
        )
        return response

    def _sign_response(self, response: list[Message], request: VerifiedServiceRequest) -> None:
        start = next(message for message in response if message["type"] == "http.response.start")
        material = b"".join(
            message.get("body", b"")
            for message in response
            if message["type"] == "http.response.body"
        )
        now = int(time.time())
        proof = jwt.encode(
            {
                "iss": self.verifier.audience,
                "aud": request.caller,
                "iat": now,
                "exp": now + _LIFETIME,
                "jti": request.nonce,
                "status": start["status"],
                "digest": hashlib.sha256(material).hexdigest(),
            },
            self.key,
            algorithm="EdDSA",
            headers={"typ": _TYPE, "kid": self.verifier.audience},
        )
        start["headers"] = [
            (key, value)
            for key, value in start.get("headers", [])
            if key not in {b"x-briareus-service-proof", b"cache-control"}
        ]
        start["headers"].extend(
            [
                (b"x-briareus-service-proof", proof.encode("ascii")),
                (b"cache-control", b"no-store"),
            ]
        )


def serve_unix(app: ASGIApp, path: str, *, diagnostics_port: int | None = None) -> None:
    """Start one independent owner, never discover or restart peer services."""
    target = Path(path)
    if not target.parent.is_dir() or target.parent.stat().st_uid != os.getuid():
        raise ValueError("Owner must own its pre-provisioned socket directory")
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_socket() or target.stat().st_uid != os.getuid():
            raise ValueError("Refusing to replace foreign owner socket")
        target.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(path)
        os.chmod(path, 0o660)
        listener.listen(128)
        diagnostics = None
        try:
            sockets = [listener]
            if diagnostics_port is not None:
                diagnostics = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                diagnostics.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                diagnostics.bind(("0.0.0.0", diagnostics_port))
                diagnostics.listen(128)
                sockets.append(diagnostics)
            uvicorn.Server(
                uvicorn.Config(app, http=UnixPeerProtocol, proxy_headers=False, access_log=False)
            ).run(sockets=sockets)
        finally:
            if diagnostics is not None:
                diagnostics.close()
            target.unlink(missing_ok=True)
