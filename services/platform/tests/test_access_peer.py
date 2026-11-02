"""The live Access peer adapter binds kernel identity, request bytes and replay."""

import hashlib
import json
import os
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from projects._oidc_access_project_api import AccessMembershipQuery
from projects.access_peer import UnixAccessProjectAuthority
from projects.infrastructure.access_evidence import VerifiedAccessRequest
from starlette.requests import Request


@dataclass(frozen=True)
class SignedRequest:
    token: str
    nonce: str
    body: bytes
    path: str


class AccessPeerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.authorization_key = Ed25519PrivateKey.generate()
        self.resource_key = Ed25519PrivateKey.generate()
        signing = Ed25519PrivateKey.generate()
        public, resource_public, private = (
            root / "auth.pub",
            root / "resource.pub",
            root / "platform.key",
        )
        public.write_bytes(
            self.authorization_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        resource_public.write_bytes(
            self.resource_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        private.write_bytes(
            signing.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        with patch.dict(os.environ, {"PLATFORM_RESOURCES_VERIFY_KEY_FILE": str(resource_public)}):
            self.authority = UnixAccessProjectAuthority(str(public), str(private))
        self.query = AccessMembershipQuery(
            issuer="https://identity.example/auth/v1/",
            subject="R" * 24,
            project_uuid=uuid4(),
        )

    def signed(
        self, *, resources: bool = False, path: str = "/internal/v1/platform/oidc/actor-context"
    ) -> SignedRequest:
        body = json.dumps(self.query.model_dump(mode="json"), separators=(",", ":")).encode()
        now, nonce = int(time.time()), str(uuid4())
        consumer = "briareus:resources" if resources else "briareus:authorization"
        token = jwt.encode(
            {
                "iss": consumer,
                "aud": "briareus:platform",
                "iat": now,
                "nbf": now,
                "exp": now + 10,
                "jti": nonce,
                "method": "POST",
                "path": path,
                "digest": hashlib.sha256(body).hexdigest(),
            },
            self.resource_key if resources else self.authorization_key,
            algorithm="EdDSA",
            headers={"typ": "briareus-service-proof+jwt", "kid": consumer},
        )
        return SignedRequest(token, nonce, body, path)

    def request(
        self, proof: SignedRequest, *, uid: int | None = 1002, body: bytes | None = None
    ) -> Request:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": proof.path,
                "briareus.unix_peer_uid": uid,
                "headers": [(b"authorization", ("Bearer " + proof.token).encode())],
            }
        )
        request._body = proof.body if body is None else body
        return request

    async def test_verified_request_carries_only_typed_consumer_and_original_nonce(self) -> None:
        proof = self.signed()
        request = self.request(proof)
        peer = await self.authority.verify(request, self.query)
        self.assertEqual(peer.consumer, "authorization")
        self.assertEqual(peer.project_uuid, self.query.project_uuid)
        self.assertEqual(
            request.scope["briareus.verified_access_request"],
            VerifiedAccessRequest("authorization", proof.nonce),
        )

    async def test_same_signed_request_cannot_be_replayed(self) -> None:
        proof = self.signed()
        await self.authority.verify(self.request(proof), self.query)
        with self.assertRaises(ValueError):
            await self.authority.verify(self.request(proof), self.query)

    async def test_kernel_identity_and_exact_body_are_independent_guards(self) -> None:
        for uid, body in ((None, None), (1000, None), (1002, b"{}")):
            with self.subTest(uid=uid, body=body), self.assertRaises(ValueError):
                await self.authority.verify(
                    self.request(self.signed(), uid=uid, body=body), self.query
                )

    async def test_resources_peer_is_limited_to_actor_context(self) -> None:
        denied = self.signed(resources=True, path="/internal/v1/platform/oidc/project-member")
        with self.assertRaises(ValueError):
            await self.authority.verify(self.request(denied, uid=1006), self.query)
        proof = self.signed(resources=True)
        peer = await self.authority.verify(self.request(proof, uid=1006), self.query)
        self.assertEqual(peer.consumer, "resources")
