"""Typed protobuf preserves canonical signed journal facts across every action."""

from __future__ import annotations

import base64
import time
import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

import grpc
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol import journal_pb2 as pb
from node_protocol.control import ControlCommand
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.forward import ForwardProof
from node_protocol.journal import (
    AcquireJournal,
    AdmitForward,
    ApplyOperation,
    ConfigureJournal,
    FindFailedCandidate,
    ForwardTarget,
    GetConfiguration,
    GetOperation,
    JournalAction,
    JournalConfiguration,
    JournalConfigurationEvent,
    JournalEvent,
    JournalOperation,
    JournalOperationEvent,
    JournalRequest,
    JournalResult,
    MatchApplied,
    PhaseOperation,
    ReadCursor,
    ReadEvents,
    ReleaseJournal,
    RenewJournal,
    ReserveOperation,
    RestoreOperation,
    SignedJournalReply,
    SignedJournalRequest,
    sign_reply,
    sign_request,
    verify_reply,
    verify_request,
)
from node_protocol.journal_grpc import (
    decode_reply,
    decode_request,
    encode_reply,
    encode_request,
    journal_call,
    register_journal,
)
from node_protocol.models import (
    Deployment,
    ModuleConfiguration,
    ModuleRelease,
    NodeBudget,
    NodeRecord,
    NodeScope,
    ResourceLimits,
    RuntimePolicy,
)

NODE = uuid4()
OPERATION = uuid4()
SESSION = uuid4()
NOW = 1_792_555_200


def deployment() -> Deployment:
    return Deployment(
        id=uuid4(),
        node_uuid=NODE,
        project_uuid=uuid4(),
        release=ModuleRelease(
            module="files", image="fixture/worker@sha256:" + "a" * 64, lifecycle="stateless"
        ),
        limits=ResourceLimits(memory_bytes=64 * 1024**2, cpu_millis=100, pids=32),
        configuration=ModuleConfiguration(runtime_policy=RuntimePolicy(web_max_tabs=None)),
    )


def node_record() -> NodeRecord:
    return NodeRecord(
        id=NODE,
        name="journal-fixture",
        scope=NodeScope(kind="shared"),
        enabled=True,
        budget=NodeBudget(
            total=ResourceLimits(memory_bytes=2 * 1024**3, cpu_millis=4000, pids=4096),
            reserved=ResourceLimits(memory_bytes=1024**3, cpu_millis=1000, pids=1024),
        ),
        created_at=datetime(2026, 10, 21, tzinfo=UTC),
    )


def diagnostic() -> FailureDiagnostic:
    return FailureDiagnostic(
        stage="checking",
        component="worker",
        reason="unhealthy",
        exit_code=0,
        health_status="none",
        oom_killed=False,
        health_exit_code=-1,
    )


def request(action: JournalAction, *, now: int = NOW) -> JournalRequest:
    return JournalRequest(
        node_uuid=NODE,
        request_uuid=uuid4(),
        session_uuid=SESSION,
        lease_epoch=None if isinstance(action, AcquireJournal) else 7,
        issued_at=now,
        expires_at=now + 15,
        payload=action,
    )


def actions(spec: Deployment, key: Ed25519PrivateKey) -> tuple[JournalAction, ...]:
    common = {
        "node_uuid": NODE,
        "operation_uuid": OPERATION,
        "sequence": 1,
        "issued_at": NOW,
        "expires_at": NOW + 15,
    }
    configure = ControlCommand.model_validate(
        {**common, "action": "configure", "node_record": node_record()}
    )
    apply = ControlCommand.model_validate({**common, "action": "apply", "deployment": spec})
    configure_signature = base64.b64encode(key.sign(configure.signing_bytes())).decode()
    apply_signature = base64.b64encode(key.sign(apply.signing_bytes())).decode()
    proof = ForwardProof(
        node_uuid=NODE,
        placement_uuid=spec.id,
        project_uuid=spec.project_uuid,
        agent_session_uuid=SESSION,
        request_uuid=uuid4(),
        grant_revision=1,
        module="files",
        fingerprint=spec.fingerprint,
        port=8000,
        body_digest="b" * 64,
        bearer_digest="c" * 64,
        effect_digest="d" * 64,
        context_digest="e" * 64,
        protocol_version="2025-11-25",
        mcp_session_id="session",
        issued_at=NOW,
        expires_at=NOW + 15,
    )
    gateway_signature = base64.b64encode(key.sign(proof.signing_bytes())).decode()
    return (
        AcquireJournal(),
        RenewJournal(lease_seconds=5),
        ReleaseJournal(),
        GetConfiguration(),
        ConfigureJournal(core_command=configure, core_signature=configure_signature),
        GetOperation(operation_uuid=OPERATION),
        ReserveOperation(core_command=apply, core_signature=apply_signature),
        PhaseOperation(
            operation_uuid=OPERATION,
            phase="failed",
            container="worker",
            error="UPDATE_FAILED",
            diagnostic=diagnostic(),
        ),
        ApplyOperation(operation_uuid=OPERATION, desired=spec, container="worker"),
        RestoreOperation(operation_uuid=OPERATION, previous=spec, container="prior-worker"),
        MatchApplied(desired=spec, container="worker"),
        FindFailedCandidate(
            desired=spec, container="worker", fingerprint="f" * 64, before_sequence=2
        ),
        ForwardTarget(proof=proof, gateway_signature=gateway_signature),
        AdmitForward(proof=proof, gateway_signature=gateway_signature),
        ReadEvents(cursor=0),
        ReadCursor(),
    )


def full_result(spec: Deployment) -> JournalResult:
    return JournalResult(
        lease_epoch=7,
        lease_expires_at=NOW + 30,
        operation=JournalOperation(
            id=str(OPERATION),
            placement=str(spec.id),
            sequence=2,
            desired=spec,
            previous=spec.model_copy(update={"enabled": False}),
            fingerprint=spec.fingerprint,
            phase="failed",
            container="worker",
            error="UPDATE_FAILED",
            diagnostic=diagnostic(),
        ),
        configuration=JournalConfiguration(sequence=1, record=node_record()),
        events=(
            JournalEvent(
                cursor=1,
                topic="operation",
                created_at="2026-10-21T12:00:00+03:00",
                payload=JournalOperationEvent(
                    operation_uuid=OPERATION,
                    sequence=2,
                    phase="failed",
                    error="UPDATE_FAILED",
                    diagnostic=diagnostic(),
                ),
            ),
            JournalEvent(
                cursor=2,
                topic="configuration",
                created_at="2026-10-21T09:00:01Z",
                payload=JournalConfigurationEvent(node_uuid=NODE, enabled=False, sequence=1),
            ),
        ),
        cursor=0,
        container="worker",
        matched=False,
        error="JOURNAL_CONFLICT",
    )


class JournalCodecTests(unittest.TestCase):
    def test_every_action_roundtrips_the_exact_signed_canonical_bytes(self) -> None:
        key = Ed25519PrivateKey.generate()
        for action in actions(deployment(), key):
            with self.subTest(action=action.action):
                original = sign_request(request(action), key)
                wire = encode_request(original)
                self.assertEqual(wire.request.WhichOneof("action"), action.action)
                decoded = decode_request(
                    pb.SignedJournalRequest.FromString(wire.SerializeToString())
                )
                self.assertEqual(decoded, original)
                self.assertEqual(decoded.request.signing_bytes(), original.request.signing_bytes())
                verify_request(decoded, key.public_key(), node_uuid=NODE, now=NOW)

    def test_complete_and_empty_results_preserve_nulls_zero_false_and_signatures(self) -> None:
        key = Ed25519PrivateKey.generate()
        original_request = request(ReadCursor())
        for result in (JournalResult(), full_result(deployment())):
            with self.subTest(result=result):
                original = sign_reply(original_request, result, key, status_code=200, now=NOW)
                wire = encode_reply(original)
                decoded = decode_reply(pb.SignedJournalReply.FromString(wire.SerializeToString()))
                self.assertEqual(decoded, original)
                self.assertEqual(decoded.reply.signing_bytes(), original.reply.signing_bytes())
                verify_reply(decoded, original_request, key.public_key(), now=NOW)

    def test_unknown_fields_missing_action_and_changed_digest_are_rejected(self) -> None:
        key = Ed25519PrivateKey.generate()
        original_request = request(ReadCursor())
        wire = encode_request(sign_request(original_request, key))
        wire.request.MergeFromString(b"\x98\x06\x01")
        with self.assertRaisesRegex(ValueError, "Unknown node protocol field"):
            decode_request(wire)
        wire = encode_request(sign_request(original_request, key))
        wire.request.ClearField("event_cursor")
        with self.assertRaisesRegex(ValueError, "Known journal action required"):
            decode_request(wire)
        reply = encode_reply(
            sign_reply(original_request, JournalResult(cursor=0), key, status_code=200, now=NOW)
        )
        reply.reply.result.cursor = 1
        with self.assertRaises(ValueError):
            decode_reply(reply)


class JournalTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_grpc_transports_one_typed_signed_exchange(self) -> None:
        node_key, owner_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        received: list[UUID] = []

        async def handle(envelope: SignedJournalRequest) -> SignedJournalReply:
            current = int(time.time())
            value = verify_request(envelope, node_key.public_key(), node_uuid=NODE, now=current)
            received.append(value.request_uuid)
            return sign_reply(
                value, JournalResult(cursor=0), owner_key, status_code=200, now=current
            )

        server = grpc.aio.server()
        register_journal(server, handle)
        port = server.add_insecure_port("127.0.0.1:0")
        self.assertGreater(port, 0)
        await server.start()
        try:
            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                original = request(ReadCursor(), now=int(time.time()))
                reply = await journal_call(channel, sign_request(original, node_key), timeout=3)
                verified = verify_reply(
                    reply, original, owner_key.public_key(), now=int(time.time())
                )
                self.assertEqual(verified.result.cursor, 0)
                self.assertEqual(received, [original.request_uuid])
        finally:
            await server.stop(0)
