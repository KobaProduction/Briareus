"""Passive Node observation uses signed control, never execution scheduling."""

import base64
import time
import unittest
from dataclasses import dataclass, field
from unittest.mock import Mock
from uuid import uuid4

import grpc
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from node_agent.application.browser_observation import ObserveBrowser
from node_agent.control_auth import ControlRejected, CoreVerifier
from node_agent.grpc_server import ControlService, register_control
from node_agent.identity import NodeIdentity

from node_protocol.browser_observation import BrowserObservationSelector
from node_protocol.control import ControlCommand
from node_protocol.domain.browser_observation import NodeBrowserObservation
from node_protocol.domain.observations import NodeFailure
from node_protocol.grpc_codec import decode_command, decode_reply, encode_command, encode_reply
from node_protocol.grpc_control import NodeControlClient
from node_protocol.replies import NodeReplyVerifier, ReplyRejected
from node_protocol.reply_wire import NodeReplyWire


def command() -> ControlCommand:
    now = int(time.time())
    return ControlCommand(
        node_uuid=uuid4(),
        operation_uuid=uuid4(),
        action="observe_browser",
        sequence=1,
        issued_at=now,
        expires_at=now + 20,
        browser_observation=BrowserObservationSelector(
            project_uuid=uuid4(),
            placement_uuid=uuid4(),
            fingerprint="a" * 64,
            actor_uuid=uuid4(),
            agent_session_uuid=uuid4(),
            grant_revision=1,
        ),
    )


def observed(value: ControlCommand) -> NodeBrowserObservation:
    if value.browser_observation is None:
        raise AssertionError("Observation selector required")
    return NodeBrowserObservation(value.browser_observation.observation(), None)


def identity() -> NodeIdentity:
    result = NodeIdentity.__new__(NodeIdentity)
    result.key = Ed25519PrivateKey.generate()
    result.public_key = (
        result.key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return result


@dataclass
class ReadPort:
    available: list[bool] = field(default_factory=lambda: [True, True])
    calls: list[str] = field(default_factory=list)

    async def current(self, _target: BrowserObservationSelector) -> bool:
        self.calls.append("current")
        return self.available.pop(0)

    async def read(self, value: ControlCommand, _signature: str) -> NodeBrowserObservation:
        self.calls.append("read")
        return observed(value)


class ObservationWireTests(unittest.TestCase):
    def test_old_command_signing_bytes_do_not_gain_a_null_selector(self) -> None:
        value = ControlCommand(
            node_uuid=uuid4(),
            operation_uuid=uuid4(),
            action="inventory",
            sequence=1,
            issued_at=100,
            expires_at=110,
        )
        self.assertNotIn("browser_observation", value.model_dump())
        self.assertEqual(decode_command(encode_command(value, b"x" * 64)), value)

    def test_observation_roundtrip_and_tampered_selector_rejection(self) -> None:
        value = command()
        signer = identity()
        signature = signer.key.sign(value.signing_bytes())
        wire = encode_command(value, signature)
        self.assertEqual(decode_command(wire), value)
        verifier = CoreVerifier(signer.public_key.encode(), value.node_uuid)
        verifier.verify(value.model_dump_json().encode(), base64.b64encode(signature).decode())
        wire.command.browser_observation.project_uuid = str(uuid4())
        changed = decode_command(wire)
        with self.assertRaises(ControlRejected):
            verifier.verify(
                changed.model_dump_json().encode(), base64.b64encode(signature).decode()
            )

    def test_signed_reply_is_bound_to_selected_session(self) -> None:
        value = command()
        signer = identity()
        envelope = signer.reply(value, 200, observed(value))
        decoded = decode_reply(encode_reply(value, envelope))
        verifier = NodeReplyVerifier(signer.public_key.encode())
        self.assertEqual(verifier.verify(value, 200, decoded), observed(value))
        other = command()
        wrong = signer.reply(value, 200, observed(other))
        with self.assertRaises(ReplyRejected):
            verifier.verify(value, 200, wrong)

    def test_observation_selector_cannot_be_smuggled_into_apply_or_inventory(self) -> None:
        value = command()
        raw = value.model_dump()
        raw["action"] = "inventory"
        with self.assertRaises(ValueError):
            ControlCommand.model_validate(raw)
        raw = value.model_dump(exclude={"browser_observation"})
        with self.assertRaises(ValueError):
            ControlCommand.model_validate(raw)


class ObservationApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rechecks_placement_after_read(self) -> None:
        port = ReadPort([True, False])
        result = await ObserveBrowser(port).execute(command(), "signed")
        self.assertEqual(result.status, 503)
        self.assertIsInstance(result.payload, NodeFailure)
        self.assertEqual(port.calls, ["current", "read", "current"])

    async def test_disabled_placement_does_not_read(self) -> None:
        port = ReadPort([False])
        result = await ObserveBrowser(port).execute(command(), "signed")
        self.assertEqual(result.status, 503)
        self.assertEqual(port.calls, ["current"])

    async def test_read_returns_unavailable_frame_without_starting_a_browser(self) -> None:
        port = ReadPort()
        value = command()
        result = await ObserveBrowser(port).execute(value, "signed")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.payload, observed(value))
        self.assertEqual(port.calls, ["current", "read", "current"])

    async def test_actual_grpc_observation_has_independent_request_and_reply_signatures(
        self,
    ) -> None:
        value = command()
        core, node = identity(), identity()
        verifier = CoreVerifier(core.public_key.encode(), value.node_uuid)

        async def handle(received: ControlCommand, _signature: str) -> tuple[int, NodeReplyWire]:
            self.assertEqual(received, value)
            return 200, node.reply(received, 200, observed(received))

        server = grpc.aio.server()
        register_control(
            server,
            ControlService(
                verifier=verifier,
                identity=node,
                handler=handle,
                journal=Mock(),
                node_uuid=value.node_uuid,
            ),
        )
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with grpc.aio.insecure_channel("127.0.0.1:" + str(port)) as channel:
                reply = await NodeControlClient(channel).ObserveBrowser(
                    encode_command(value, core.key.sign(value.signing_bytes())),
                    timeout=5,
                )
                self.assertEqual(
                    NodeReplyVerifier(node.public_key.encode()).verify(
                        value, 200, decode_reply(reply)
                    ),
                    observed(value),
                )
        finally:
            await server.stop(0)
