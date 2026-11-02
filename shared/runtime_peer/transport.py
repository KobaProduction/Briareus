"""Body-bound, replay-protected service proofs over a kernel-authenticated UDS.

These proofs identify services, never users and never Cedar grants. Each owner
must still resolve the real Rauthy subject and current resource permissions.
No bearer issued here is accepted as an OAuth access token.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import http.client
import json
import logging
import os
import socket
import stat
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

_TYPE = "briareus-service-proof+jwt"
_LIFETIME = 10
_MAX_BODY = 65_536
_MAX_RESPONSE = 1_048_576


@dataclass(frozen=True, slots=True)
class VerifiedOwnerReply[ReplyT]:
    """Owner status and JSON body bound to the verified request nonce and proof."""

    status: int
    body: ReplyT


class PeerRejected(ValueError):
    """The service, operation binding, deadline or reply was not verified."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


@dataclass(frozen=True, slots=True)
class PeerIdentity:
    name: str
    uid: int
    public_key: Ed25519PublicKey

    @classmethod
    def from_file(cls, name: str, uid: int, path: str) -> PeerIdentity:
        key = serialization.load_pem_public_key(Path(path).read_bytes())
        if not isinstance(key, Ed25519PublicKey) or uid < 0 or not name:
            raise ValueError("Explicit service identity and Ed25519 key required")
        return cls(name, uid, key)


@dataclass(frozen=True, slots=True)
class VerifiedServiceRequest:
    caller: str
    nonce: str


def _private_key(path: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Ed25519 service signing key required")
    return key


class PeerVerifier:
    """One owner-local verifier; replay state must live for the listener lifetime."""

    def __init__(self, audience: str, callers: tuple[PeerIdentity, ...]) -> None:
        if not audience or not callers or len({p.name for p in callers}) != len(callers):
            raise ValueError("Unique explicit caller identities required")
        self.audience = audience
        self.callers = {peer.name: peer for peer in callers}
        self._used: dict[str, float] = {}

    def verify(self, *, token: str, uid: int | None, method: str, path: str, body: bytes) -> str:
        return self.verify_request(token=token, uid=uid, method=method, path=path, body=body).caller

    def verify_request(
        self, *, token: str, uid: int | None, method: str, path: str, body: bytes
    ) -> VerifiedServiceRequest:
        if len(token) > 8192 or len(body) > _MAX_BODY:
            raise PeerRejected("Service request too large")
        stage = "header"
        try:
            header = jwt.get_unverified_header(token)
            if header.get("typ") != _TYPE or set(header) - {"typ", "alg", "kid"}:
                raise ValueError("Invalid service proof header")
            peer = self.callers[header["kid"]]
            stage = "kernel_peer"
            if uid != peer.uid:
                raise ValueError("Kernel caller does not match service")
            stage = "signature"
            claims = jwt.decode(
                token,
                peer.public_key,
                algorithms=["EdDSA"],
                issuer=peer.name,
                audience=self.audience,
                options={
                    "require": [
                        "iss",
                        "aud",
                        "iat",
                        "nbf",
                        "exp",
                        "jti",
                        "method",
                        "path",
                        "digest",
                    ]
                },
            )
            nonce = claims["jti"]
            stage = "operation_binding"
            if (
                type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= _LIFETIME
                or claims["nbf"] != claims["iat"]
                or UUID(nonce).version != 4
                or str(UUID(nonce)) != nonce
                or claims["method"] != method
                or claims["path"] != path
                or not hmac.compare_digest(claims["digest"], hashlib.sha256(body).hexdigest())
            ):
                raise ValueError("Request proof does not bind this operation")
            instant = time.monotonic()
            self._used = {key: expiry for key, expiry in self._used.items() if expiry > instant}
            key = peer.name + ":" + nonce
            if key in self._used or len(self._used) >= 8192:
                raise ValueError("Replay or owner replay capacity reached")
            self._used[key] = instant + _LIFETIME + 1
            return VerifiedServiceRequest(caller=peer.name, nonce=nonce)
        except (jwt.PyJWTError, KeyError, ValueError, TypeError, AttributeError) as error:
            logging.getLogger(__name__).warning(
                "service peer rejected owner=%s stage=%s category=%s",
                self.audience,
                stage,
                type(error).__name__,
            )
            raise PeerRejected("Private service request not authenticated") from None


class PeerClient:
    """Fixed owner socket and service identity; no caller-selected upstream URL."""

    def __init__(
        self, *, name: str, signing_key_file: str, socket_path: str, owner: PeerIdentity
    ) -> None:
        self.name, self.path, self.owner = name, socket_path, owner
        self.key = _private_key(signing_key_file)

    def _connect(self) -> socket.socket:
        metadata = os.stat(self.path)
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != self.owner.uid
            or metadata.st_mode & 0o007
        ):
            raise PeerRejected("Owner socket identity invalid")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(2)
            probe.connect(self.path)
            _, uid, _ = struct.unpack(
                "3i", probe.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if uid != self.owner.uid:
                raise PeerRejected("Owner process identity invalid")
            probe.settimeout(12)
            return probe
        except BaseException:
            probe.close()
            raise

    def _send(self, path: str, body: bytes, token: str) -> tuple[int, bytes, str]:
        peer = self

        class UnixConnection(http.client.HTTPConnection):
            def connect(self) -> None:
                self.sock = peer._connect()

        connection = UnixConnection("owner", timeout=12)
        try:
            connection.request(
                "POST",
                path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token,
                    "Connection": "close",
                },
            )
            reply = connection.getresponse()
            proofs = [
                value
                for key, value in reply.getheaders()
                if key.lower() == "x-briareus-service-proof"
            ]
            if len(proofs) != 1 or len(proofs[0]) > 8192:
                raise PeerRejected("One bounded owner response proof required")
            output = reply.read(_MAX_RESPONSE + 1)
            if len(output) > _MAX_RESPONSE:
                raise PeerRejected("Owner reply too large")
            return reply.status, output, proofs[0]
        finally:
            connection.close()

    async def call[ReplyT](
        self,
        path: str,
        payload: dict[str, object],
        *,
        decode: Callable[[int, object], ReplyT],
    ) -> VerifiedOwnerReply[ReplyT]:
        if not path.startswith("/internal/v1/") or any(ch in path for ch in "?#%"):
            raise ValueError("Canonical private owner path required")
        body = canonical_json(payload)
        if len(body) > _MAX_BODY:
            raise ValueError("Owner command too large")
        now, nonce = int(time.time()), str(uuid4())
        token = jwt.encode(
            {
                "iss": self.name,
                "aud": self.owner.name,
                "iat": now,
                "nbf": now,
                "exp": now + _LIFETIME,
                "jti": nonce,
                "method": "POST",
                "path": path,
                "digest": hashlib.sha256(body).hexdigest(),
            },
            self.key,
            algorithm="EdDSA",
            headers={"typ": _TYPE, "kid": self.name},
        )
        status, output, proof = await asyncio.to_thread(self._send, path, body, token)
        try:
            header = jwt.get_unverified_header(proof)
            if header.get("typ") != _TYPE or header.get("kid") != self.owner.name:
                raise ValueError("Owner proof type invalid")
            claims = jwt.decode(
                proof,
                self.owner.public_key,
                algorithms=["EdDSA"],
                issuer=self.owner.name,
                audience=self.name,
                options={"require": ["iss", "aud", "iat", "exp", "jti", "status", "digest"]},
            )
            if (
                type(claims["iat"]) is not int
                or type(claims["exp"]) is not int
                or not 0 < claims["exp"] - claims["iat"] <= _LIFETIME
                or claims["jti"] != nonce
                or claims["status"] != status
                or not hmac.compare_digest(claims["digest"], hashlib.sha256(output).hexdigest())
            ):
                raise ValueError("Owner response binding invalid")
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError("Object owner reply required")
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise PeerRejected("Owner response not authenticated") from None
        # The owner-specific decoder runs only after all proof bindings pass.
        # Its validation failures are not authentication failures.
        return VerifiedOwnerReply(status=status, body=decode(status, result))

    async def close(self) -> None:
        # Every bounded RPC owns and closes its connection.
        return None
