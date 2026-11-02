"""Real service signatures, replay rejection and durable enrollment configuration."""

import asyncio
import base64
import tempfile
import time
import unittest
from pathlib import Path
from typing import Literal
from uuid import uuid4

from control_fixture import ControlRuntimeFixture, NoEffectsScheduler
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from journal_fixture import JournalFixture as Journal
from node_agent.application.control import NodeControl
from node_agent.control_auth import CoreVerifier
from node_agent.identity import NodeIdentity
from test_reconciliation import fixture

from node_protocol import NodeRecord
from node_protocol.control import ControlCommand
from node_protocol.domain.observations import NodeConfiguration, NodeReply
from node_protocol.replies import NodeReplyVerifier, ReplyRejected
from node_protocol.reply_wire import ConfigurationWire


class IdentityTests(unittest.TestCase):
    def command(
        self,
        node: NodeRecord,
        *,
        action: Literal["inventory", "configure"] = "inventory",
        sequence: int = 1,
        node_record: NodeRecord | None = None,
    ) -> ControlCommand:
        now = int(time.time())
        return ControlCommand(
            node_uuid=node.id,
            operation_uuid=uuid4(),
            action=action,
            sequence=sequence,
            node_record=node_record,
            issued_at=now,
            expires_at=now + 30,
        )

    def test_persistent_key_and_response_substitution_denial(self) -> None:
        node, _ = fixture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "identity.key"
            identity = NodeIdentity(path)
            self.assertEqual(NodeIdentity(path).public_key, identity.public_key)
            verifier = NodeReplyVerifier(identity.public_key.encode())
            command = self.command(node)
            payload = NodeConfiguration(node.id, 1, False)
            envelope = identity.reply(command, 200, payload)
            assert isinstance(envelope.result, ConfigurationWire)
            self.assertEqual(verifier.verify(command, 200, envelope), payload)
            for wrong_command, wrong_status, wrong_envelope in [
                (self.command(node), 200, envelope),
                (command, 503, envelope),
                (
                    command,
                    200,
                    envelope.model_copy(
                        update={"result": envelope.result.model_copy(update={"enabled": True})}
                    ),
                ),
                (
                    command,
                    200,
                    envelope.model_copy(
                        update={"proof": envelope.proof.model_copy(update={"expires_at": 1})}
                    ),
                ),
            ]:
                with self.assertRaises(ReplyRejected):
                    verifier.verify(wrong_command, wrong_status, wrong_envelope)
            other = NodeIdentity(Path(folder) / "other.key")
            with self.assertRaises(ReplyRejected):
                NodeReplyVerifier(other.public_key.encode()).verify(command, 200, envelope)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                NodeIdentity(path)

    def test_signed_configuration_is_monotonic_and_survives_restart(self) -> None:
        async def scenario() -> None:
            node, _ = fixture()
            node = node.model_copy(update={"enabled": False})
            key = Ed25519PrivateKey.generate()
            public = key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            with tempfile.TemporaryDirectory() as folder:
                journal = Journal(Path(folder) / "journal-fixture")
                identity = NodeIdentity(Path(folder) / "identity.key")
                verifier = NodeReplyVerifier(identity.public_key.encode())
                service = NodeControl(
                    node, ControlRuntimeFixture(node), journal, NoEffectsScheduler()
                )

                async def send(command: ControlCommand, status: int) -> NodeReply:
                    accepted = CoreVerifier(public, node.id).verify(
                        command.model_dump_json().encode(),
                        base64.b64encode(key.sign(command.signing_bytes())).decode(),
                    )
                    result = await service.execute(accepted)
                    self.assertEqual(result.status, status)
                    return verifier.verify(
                        command, status, identity.reply(command, result.status, result.payload)
                    )

                record = node.model_copy(update={"enabled": True})
                command = self.command(node, action="configure", node_record=record, sequence=2)
                accepted = await send(command, 200)
                assert isinstance(accepted, NodeConfiguration)
                self.assertTrue(accepted.enabled)
                await send(command, 200)
                await send(
                    self.command(node, action="configure", node_record=node, sequence=1), 409
                )
                await send(
                    self.command(node, action="configure", node_record=node, sequence=2), 409
                )
                changed_budget = node.budget.model_copy(
                    update={
                        "total": node.budget.total.model_copy(
                            update={"memory_bytes": node.budget.total.memory_bytes * 2}
                        )
                    }
                )
                await send(
                    self.command(
                        node,
                        action="configure",
                        sequence=3,
                        node_record=record.model_copy(update={"budget": changed_budget}),
                    ),
                    409,
                )
                (await journal.close())
                journal = Journal(Path(folder) / "journal-fixture")
                # The disabled bootstrap must restore the signed Core configuration.
                restored = ControlRuntimeFixture(node)
                await NodeControl(node, restored, journal, NoEffectsScheduler()).initialize()
                self.assertTrue(restored.record.enabled)
                (await journal.close())

        asyncio.run(scenario())
