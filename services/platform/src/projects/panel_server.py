"""Platform launcher with a peer-authenticated, owner-local Unix API listener.

TCP remains available for diagnostics; private context requests on TCP cannot
provide the kernel peer credentials required by the attestor.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import socket
import stat
import struct
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Request
from pydantic import SecretStr
from starlette.types import Receive, Scope, Send
from uvicorn.protocols.http.h11_impl import H11Protocol

from common.owner_runtime import VerifiedOwnerIngress
from projects.domain.context import ContextSelector
from projects.infrastructure.panel_delegation import PanelDelegationClaims, decode_delegation
from projects.presentation.management_inputs import ManagementQuery

from ._oidc_context_api import (
    PanelContextNotAuthenticated,
    PlatformContextQuery,
    VerifiedPanelContextPeer,
)
from .control_runtime import create_platform_app


class UnixPanelAuthority:
    def __init__(self, socket_path: str, public_key_file: str) -> None:
        self.path = socket_path
        self.public_key_file = public_key_file
        self.key: Ed25519PublicKey | None = None

    def verification_key(self) -> Ed25519PublicKey:
        if self.key is not None:
            return self.key
        key = serialization.load_pem_public_key(Path(self.public_key_file).read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Panel service verification requires Ed25519")
        self.key = key
        return key

    async def verify_running_ingress(self) -> VerifiedOwnerIngress:
        await asyncio.to_thread(self.verification_key)
        info = os.stat(self.path)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 1000 or info.st_mode & 0o007:
            raise ValueError("Private Platform socket unavailable")
        return VerifiedOwnerIngress(
            "platform", "unix-peer", True, datetime.now(UTC) + timedelta(seconds=15)
        )

    async def verify(
        self, request: Request, query: PlatformContextQuery, *, purpose: str = "platform-current-v1"
    ) -> VerifiedPanelContextPeer:
        if request.scope.get("briareus.unix_peer_uid") != 1001:
            raise PanelContextNotAuthenticated("Control Panel kernel peer required")
        bearer = request.headers.get("authorization", "")
        if not bearer.startswith("Bearer ") or len(bearer) > 8192:
            raise PanelContextNotAuthenticated("Signed Panel delegation required")
        try:
            claims = decode_delegation(bearer[7:], await asyncio.to_thread(self.verification_key))
            peer = claims.peer(
                ContextSelector(query.issuer, query.subject, query.project_uuid), purpose
            )
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise PanelContextNotAuthenticated("Invalid Panel delegation") from None
        request.scope["briareus.verified_panel_claims"] = claims
        return peer

    async def verify_management(self, request: Request, query: ManagementQuery) -> datetime:
        peer = await self.verify(
            request,
            PlatformContextQuery(issuer=query.issuer, subject=query.subject),
            purpose="platform-management-v1",
        )
        expected = query.fingerprint()
        claims = request.scope["briareus.verified_panel_claims"]
        if not isinstance(claims, PanelDelegationClaims) or claims.command_digest is None:
            raise PanelContextNotAuthenticated("Management command scope mismatch")
        if not hmac.compare_digest(claims.command_digest, expected):
            raise PanelContextNotAuthenticated("Management command scope mismatch")
        return peer.expires_at


class UnixPeerProtocol(H11Protocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        if not isinstance(transport, asyncio.Transport):
            raise TypeError("Platform HTTP requires a stream transport")
        super().connection_made(transport)
        connection = transport.get_extra_info("socket")
        uid = None
        if connection is not None and connection.family == socket.AF_UNIX:
            _, uid, _ = struct.unpack(
                "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
        application = self.app

        async def with_peer(scope: Scope, receive: Receive, send: Send) -> None:
            scope = {**scope, "briareus.unix_peer_uid": uid}
            await application(scope, receive, send)

        self.app = with_peer


def serve() -> None:
    path = os.environ["PLATFORM_PANEL_SOCKET"]
    authority = UnixPanelAuthority(path, os.environ["PLATFORM_PANEL_VERIFY_KEY_FILE"])
    access_authority = None
    if os.environ.get("PLATFORM_ACCESS_VERIFY_KEY_FILE"):
        from .access_peer import UnixAccessProjectAuthority

        access_authority = UnixAccessProjectAuthority(
            os.environ["PLATFORM_ACCESS_VERIFY_KEY_FILE"],
            os.environ["PLATFORM_ACCESS_SIGNING_KEY_FILE"],
        )
    key_file = os.environ["RAUTHY_USERS_READ_KEY_FILE"]
    managed = os.environ.get("PLATFORM_MANAGED_PEER") == "1"
    key = None if managed else SecretStr(Path(key_file).read_text().strip())
    target = Path(path)
    # Independently deployed API init owns the shared public-key directory.
    # No cross-application depends_on or peer restart is performed here.
    deadline = time.monotonic() + 120
    while not target.parent.is_dir() and time.monotonic() < deadline:
        time.sleep(1)
    if target.exists():
        if not target.is_socket() or target.stat().st_uid != os.getuid():
            raise ValueError("Refusing to replace foreign Platform socket")
        target.unlink()
    unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        unix.bind(path)
        os.chmod(path, 0o660)
        unix.listen(128)
        tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp.bind(("0.0.0.0", 8000))
        tcp.listen(128)
        app = create_platform_app(
            trusted_ingress=authority,
            panel_attestor=authority,
            access_attestor=access_authority,
            users_read_api_key=key,
            users_read_key_file=key_file if managed else None,
        )
        uvicorn.Server(
            uvicorn.Config(app, http=UnixPeerProtocol, proxy_headers=False, access_log=False)
        ).run(sockets=[unix, tcp])
    finally:
        unix.close()
        tcp.close()


def main() -> None:
    if os.environ.get("PLATFORM_PANEL_SOCKET"):
        serve()
    else:
        uvicorn.run("projects.control_runtime:app", host="0.0.0.0", port=8000, proxy_headers=False)


if __name__ == "__main__":
    main()
