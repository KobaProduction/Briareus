"""Real service signatures, replay rejection and durable enrollment configuration."""
import asyncio
import base64
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol.control import ControlCommand
from node_protocol.replies import NodeReplyVerifier, ReplyRejected
from node_agent.control_auth import CoreVerifier
from node_agent.identity import NodeIdentity
from node_agent.journal import Journal
from node_agent.server import create_app
from test_reconciliation import FakeEngine, fixture


class IdentityTests(unittest.TestCase):
    def command(self, node, **changes):
        now = int(time.time())
        fields = dict(node_uuid=node.id, operation_uuid=uuid4(), action="inventory",
                      sequence=1, issued_at=now, expires_at=now + 30)
        fields.update(changes)
        return ControlCommand(**fields)

    def test_persistent_key_and_response_substitution_denial(self):
        node, _ = fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "identity.key"
            identity = NodeIdentity(path)
            self.assertEqual(NodeIdentity(path).public_key, identity.public_key)
            verifier = NodeReplyVerifier(identity.public_key.encode())
            command = self.command(node)
            envelope = identity.reply(command, 200, {"enabled": False})
            self.assertEqual(verifier.verify(command, 200, envelope), {"enabled": False})
            for wrong_command, wrong_status, wrong_envelope in [
                (self.command(node), 200, envelope),
                (command, 503, envelope),
                (command, 200, {**envelope, "result": {"enabled": True}}),
                (command, 200, {**envelope, "proof": {**envelope["proof"], "expires_at": 1}}),
            ]:
                with self.assertRaises(ReplyRejected):
                    verifier.verify(wrong_command, wrong_status, wrong_envelope)
            other = NodeIdentity(Path(folder) / "other.key")
            with self.assertRaises(ReplyRejected):
                NodeReplyVerifier(other.public_key.encode()).verify(command, 200, envelope)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                NodeIdentity(path)

    def test_signed_configuration_is_monotonic_and_survives_restart(self):
        async def scenario():
            node, _ = fixture()
            node = node.model_copy(update={"enabled": False})
            key = Ed25519PrivateKey.generate()
            public = key.public_key().public_bytes(serialization.Encoding.PEM,
                        serialization.PublicFormat.SubjectPublicKeyInfo)
            with tempfile.TemporaryDirectory() as folder:
                journal = Journal(Path(folder) / "journal.sqlite")
                identity = NodeIdentity(Path(folder) / "identity.key")
                verifier = NodeReplyVerifier(identity.public_key.encode())
                app = create_app(node, FakeEngine(), journal, CoreVerifier(public, node.id), identity)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://node") as client:
                    async def send(command, status):
                        accepted=CoreVerifier(public,node.id).verify(command.model_dump_json().encode(),
                            base64.b64encode(key.sign(command.signing_bytes())).decode())
                        actual,envelope=await app.state.node_control(accepted)
                        self.assertEqual(actual,status)
                        return verifier.verify(command,status,envelope)
                    record = node.model_copy(update={"enabled": True})
                    command = self.command(node, action="configure", node_record=record, sequence=2)
                    self.assertTrue((await send(command, 200))["enabled"])
                    await send(command, 200)
                    await send(self.command(node, action="configure", node_record=node, sequence=1), 409)
                    await send(self.command(node, action="configure", node_record=node, sequence=2), 409)
                    changed_budget = node.budget.model_copy(update={"total": node.budget.total.model_copy(
                        update={"memory_bytes": node.budget.total.memory_bytes * 2})})
                    await send(self.command(node, action="configure", sequence=3,
                        node_record=record.model_copy(update={"budget": changed_budget})), 409)
                journal.close()
                journal = Journal(Path(folder) / "journal.sqlite")
                # Loading with the original disabled bootstrap restores the signed Core configuration.
                create_app(node, FakeEngine(), journal, CoreVerifier(public, node.id), identity)
                self.assertTrue(__import__("json").loads(journal.configuration()["record"])["enabled"])
                journal.close()
        asyncio.run(scenario())
