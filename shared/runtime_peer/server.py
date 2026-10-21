"""Private owner listener: OS peer identity plus operation-bound signatures."""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import struct
import time
from pathlib import Path

import jwt
import uvicorn
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.protocols.http.h11_impl import H11Protocol

from .transport import PeerRejected, PeerVerifier, _LIFETIME, _MAX_BODY, _MAX_RESPONSE, _TYPE, _private_key


class UnixPeerProtocol(H11Protocol):
    def connection_made(self, transport: asyncio.Transport) -> None:
        super().connection_made(transport)
        connection = transport.get_extra_info("socket")
        uid = None
        if connection is not None and connection.family == socket.AF_UNIX:
            _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        application = self.app

        async def with_peer(scope: Scope, receive: Receive, send: Send) -> None:
            await application({**scope, "briareus.unix_peer_uid": uid}, receive, send)

        self.app = with_peer


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
        if (scope.get("method") in {"GET", "HEAD"}
            and scope.get("path") in {"/health/live", "/health/ready"}
            and not scope.get("query_string")):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        try:
            async with asyncio.timeout(3):
                while True:
                    message = await receive()
                    if message["type"] != "http.request":
                        raise PeerRejected("Request disconnected")
                    body.extend(message.get("body", b""))
                    if len(body) > _MAX_BODY:
                        raise PeerRejected("Request too large")
                    if not message.get("more_body", False):
                        break
            headers = scope.get("headers", [])
            authorization = [v for k, v in headers if k == b"authorization"]
            if (len(authorization) != 1 or not authorization[0].startswith(b"Bearer ")
                or any(k in {b"cookie", b"origin"} for k, _ in headers)
                or scope.get("query_string") or scope.get("method") != "POST"
                or scope.get("raw_path") != scope["path"].encode("ascii")
                or not scope["path"].startswith("/internal/v1/")):
                raise PeerRejected("Private RPC envelope required")
            token = authorization[0][7:].decode("ascii")
            caller = self.verifier.verify(token=token, uid=scope.get("briareus.unix_peer_uid"),
                                          method=scope["method"], path=scope["path"], body=bytes(body))
            nonce = jwt.decode(token, options={"verify_signature": False})["jti"]
        except (PeerRejected, TimeoutError, UnicodeError, KeyError, ValueError):
            await JSONResponse({"error": {"code": "SERVICE_PEER_REQUIRED"}}, status_code=401)(scope, receive, send)
            return

        delivered = False

        async def original_body() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        response: list[Message] = []
        size = 0

        async def capture(message: Message) -> None:
            nonlocal size
            if message["type"] == "http.response.body":
                size += len(message.get("body", b""))
                if size > _MAX_RESPONSE:
                    raise PeerRejected("Owner output too large")
            response.append(message)

        await self.app({**scope, "briareus.service_peer": caller}, original_body, capture)
        start = next(m for m in response if m["type"] == "http.response.start")
        material = b"".join(m.get("body", b"") for m in response if m["type"] == "http.response.body")
        now = int(time.time())
        proof = jwt.encode({"iss": self.verifier.audience, "aud": caller,
                            "iat": now, "exp": now + _LIFETIME, "jti": nonce,
                            "status": start["status"], "digest": hashlib.sha256(material).hexdigest()},
                           self.key, algorithm="EdDSA",
                           headers={"typ": _TYPE, "kid": self.verifier.audience})
        start["headers"] = [(k, v) for k, v in start.get("headers", [])
                            if k not in {b"x-briareus-service-proof", b"cache-control"}]
        start["headers"].extend([(b"x-briareus-service-proof", proof.encode("ascii")),
                                 (b"cache-control", b"no-store")])
        for message in response:
            await send(message)


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
            uvicorn.Server(uvicorn.Config(app, http=UnixPeerProtocol, proxy_headers=False,
                                          access_log=False)).run(sockets=sockets)
        finally:
            if diagnostics is not None:
                diagnostics.close()
            target.unlink(missing_ok=True)
