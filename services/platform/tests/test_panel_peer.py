"""Regression coverage for private Panel delegation boundaries."""

import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from projects._oidc_context_api import PanelContextNotAuthenticated, PlatformContextQuery
from projects.panel_server import UnixPanelAuthority
from starlette.requests import Request


class PanelPeerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.key = Ed25519PrivateKey.generate()
        public = Path(self.directory.name) / "panel.pub"
        public.write_bytes(
            self.key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        self.authority = UnixPanelAuthority("unused", str(public))
        self.query = PlatformContextQuery(
            issuer="https://identity.example/auth/v1/", subject="user"
        )

    def request(
        self,
        *,
        uid: int | None = 1001,
        key: Ed25519PrivateKey | None = None,
        changes: dict[str, object] | None = None,
    ) -> Request:
        now = int(datetime.now(UTC).timestamp())
        claims: dict[str, object] = {
            "iss": "briareus:control-panel-api",
            "aud": "briareus:platform",
            "sub": "user",
            "rauthy_issuer": self.query.issuer,
            "project_uuid": None,
            "purpose": "platform-current-v1",
            "iat": now,
            "nbf": now,
            "exp": now + 15,
            "jti": str(uuid4()),
        }
        claims.update(changes or {})
        token = jwt.encode(
            claims,
            key or self.key,
            algorithm="EdDSA",
            headers={"typ": "briareus-panel-delegation+jwt"},
        )
        return Request(
            {
                "type": "http",
                "briareus.unix_peer_uid": uid,
                "headers": [(b"authorization", ("Bearer " + token).encode())],
            }
        )

    async def test_accepts_bound_kernel_peer_and_signature(self) -> None:
        result = await self.authority.verify(self.request(), self.query)
        self.assertEqual(result.subject, "user")

    async def test_denies_network_peer_and_wrong_process(self) -> None:
        for uid in (None, 1000, 1002):
            with self.subTest(uid=uid), self.assertRaises(PanelContextNotAuthenticated):
                await self.authority.verify(self.request(uid=uid), self.query)

    async def test_denies_forgery_and_query_substitution(self) -> None:
        with self.assertRaises(PanelContextNotAuthenticated):
            await self.authority.verify(self.request(key=Ed25519PrivateKey.generate()), self.query)
        now = int(datetime.now(UTC).timestamp())
        for changes in (
            {"sub": "other"},
            {"project_uuid": str(uuid4())},
            {"exp": now - 1},
            {"exp": now + 60},
            {"rauthy_issuer": "https://other.example/"},
        ):
            with (
                self.subTest(changes=list(changes)),
                self.assertRaises(PanelContextNotAuthenticated),
            ):
                await self.authority.verify(self.request(changes=changes), self.query)

    async def test_management_signature_binds_the_complete_command_payload(self) -> None:
        payload: dict[str, object] = {
            "issuer": self.query.issuer,
            "subject": self.query.subject,
            "operation_uuid": str(uuid4()),
            "action": "team.create",
            "data": {"name": "Team"},
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        request = self.request(
            changes={"purpose": "platform-management-v1", "command_digest": digest}
        )
        self.assertGreater(
            await self.authority.verify_management(request, payload), datetime.now(UTC)
        )
        with self.assertRaises(PanelContextNotAuthenticated):
            await self.authority.verify_management(
                request, {**payload, "operation_uuid": str(uuid4())}
            )
        with self.assertRaises(PanelContextNotAuthenticated):
            await self.authority.verify_management(request, {**payload, "data": {"name": "Other"}})

    async def test_current_context_proof_cannot_be_reused_for_a_management_command(self) -> None:
        with self.assertRaises(PanelContextNotAuthenticated):
            await self.authority.verify_management(
                self.request(), {"issuer": self.query.issuer, "subject": self.query.subject}
            )
