"""Signed control-plane commands cannot be substituted across nodes/operations."""
import asyncio
import base64
import time
import unittest
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_agent.control_auth import ControlCommand, ControlRejected, CoreVerifier
from node_agent.server import create_app
from test_reconciliation import FakeEngine, fixture


class ControlAuthTests(unittest.TestCase):
    def setUp(self):
        self.node, self.spec = fixture()
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(serialization.Encoding.PEM,
                                                    serialization.PublicFormat.SubjectPublicKeyInfo)
        self.verifier = CoreVerifier(public, self.node.id)

    def command(self):
        now = int(time.time())
        return ControlCommand(node_uuid=self.node.id, operation_uuid=uuid4(), action="apply",
                              sequence=1, issued_at=now, expires_at=now + 30, deployment=self.spec)

    def sign(self, command):
        return base64.b64encode(self.key.sign(command.signing_bytes())).decode()

    def test_exact_command_and_cross_node_denial(self):
        command = self.command()
        signature = self.sign(command)
        self.assertEqual(self.verifier.verify(command.model_dump_json().encode(), signature), command)
        other = command.model_copy(update={"node_uuid": uuid4(), "deployment": None, "action": "status"})
        with self.assertRaises(ControlRejected):
            self.verifier.verify(other.model_dump_json().encode(), self.sign(other))

    def test_reject_tampered_operation_signature_and_expiry(self):
        command = self.command()
        signature = self.sign(command)
        for invalid in [command.model_copy(update={"operation_uuid": uuid4()}),
                        command.model_copy(update={"sequence": 2})]:
            with self.assertRaises(ControlRejected):
                self.verifier.verify(invalid.model_dump_json().encode(), signature)
        expired = command.model_copy(update={"issued_at": 1, "expires_at": 30})
        with self.assertRaises(ControlRejected):
            self.verifier.verify(expired.model_dump_json().encode(), self.sign(expired))
        with self.assertRaises(ControlRejected):
            self.verifier.verify(command.model_dump_json().encode(), "not-base64")

    def test_listener_denies_unsigned_and_browser_requests(self):
        async def scenario():
            # Journal is never accessed before service authentication.
            app = create_app(self.node, FakeEngine(), None, self.verifier)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://node") as client:
                command = self.command()
                raw = command.model_dump_json()
                headers = {"content-type": "application/json"}
                response = await client.post("/internal/v1/node/control", content=raw, headers=headers)
                self.assertEqual(response.status_code, 404)
                headers["x-briareus-core-signature"] = self.sign(command)
                headers["origin"] = "http://127.0.0.1"
                response = await client.post("/internal/v1/node/control", content=raw, headers=headers)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("deployment", response.text)
        asyncio.run(scenario())
