"""Node installation gets explicit public journal transport trust, never private keys."""

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from projects._node_persistence import NodeRow
from projects.infrastructure.node_setup import NodeJournalSetup
from projects.node_control import NodeControl

from node_protocol import NodeBudget, ResourceLimits


def public_ca(key: Ed25519PrivateKey) -> str:
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Journal test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, None)
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode()


class NodeSetupTests(unittest.TestCase):
    def test_journal_target_rejects_implicit_or_ambiguous_transport(self) -> None:
        certificate = public_ca(Ed25519PrivateKey.generate())
        for target in (
            "resources",
            "https://resources:8001",
            "user@resources:8001",
            "resources:8001/path",
            "resources:8001?x=1",
            "resources:8001#x",
            "resources:0",
            "resources:65536",
            "resources :8001",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                NodeJournalSetup(target=target, ca_certificate=certificate)

    def test_explicit_public_ca_file_is_bounded_and_no_private_material_is_accepted(self) -> None:
        key = Ed25519PrivateKey.generate()
        certificate = public_ca(key)
        self.assertIsNone(NodeJournalSetup.from_environment({}))
        with self.assertRaises(ValueError):
            NodeJournalSetup.from_environment(
                {"RESOURCES_NODE_JOURNAL_TARGET": "resources.example:8001"}
            )
        private = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        with self.assertRaises(ValueError):
            NodeJournalSetup(target="resources.example:8001", ca_certificate=private)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "public-ca.pem"
            path.write_text(certificate, encoding="ascii")
            configured = NodeJournalSetup.from_environment(
                {
                    "RESOURCES_NODE_JOURNAL_TARGET": "resources.example:8001",
                    "RESOURCES_NODE_JOURNAL_CA_FILE": str(path),
                }
            )
        self.assertEqual(
            configured,
            NodeJournalSetup(target="resources.example:8001", ca_certificate=certificate),
        )

    def test_setup_requires_journal_and_serializes_existing_public_fields(self) -> None:
        key = Ed25519PrivateKey.generate()
        public = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
        budget = NodeBudget(
            total=ResourceLimits(memory_bytes=1024**3, cpu_millis=2000, pids=512),
            reserved=ResourceLimits(memory_bytes=384 * 1024**2, cpu_millis=750, pids=192),
        )
        row = NodeRow(
            id=uuid4(),
            name="Node",
            scope="shared",
            owner_uuid=None,
            host_uuid=uuid4(),
            runtime_uid=2201,
            endpoint="https://node.example",
            budget=budget.model_dump(mode="json"),
            enabled=False,
            created_at=datetime.now(UTC),
        )
        control = NodeControl(key, frozenset({row.endpoint}), gateway_verify_key=public)
        with self.assertRaises(ValueError):
            control.setup(row)
        journal = NodeJournalSetup(target="resources.example:8001", ca_certificate=public_ca(key))
        configured = NodeControl(
            key, frozenset({row.endpoint}), gateway_verify_key=public, journal_setup=journal
        )
        result = configured.setup(row)
        self.assertEqual(result.node_record.id, row.id)
        self.assertEqual(result.journal, journal)
        self.assertEqual(result.runtime_uid, 2201)
        self.assertEqual(
            result.rootless_budget,
            ResourceLimits(memory_bytes=768 * 1024**2, cpu_millis=1500, pids=384),
        )
        self.assertNotIn("PRIVATE KEY", result.model_dump_json())
