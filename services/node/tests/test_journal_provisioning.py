"""Public journal trust is explicit, repeatable and never silently replaced."""

import json
import os
import stat
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from local.provision import (
    ensure_journal_environment,
    journal_configuration,
    write_journal_trust,
)

from node_protocol.setup import JournalSetup


def public_ca(*, expired: bool = False) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Disposable journal fixture")]
    )
    now = datetime.now(UTC)
    end = now - timedelta(days=1) if expired else now + timedelta(days=1)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=2))
        .not_valid_after(end)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode()


class ProvisioningTests(unittest.TestCase):
    def test_only_explicit_tls_target_and_current_public_certificate_are_accepted(self) -> None:
        certificate = public_ca()
        valid = journal_configuration(
            JournalSetup(target="resources.example:8001", ca_certificate=certificate)
        )
        self.assertEqual(valid.target, "resources.example:8001")
        self.assertEqual(valid.ca_certificate, certificate.encode())
        for target in (
            "resources.example",
            "https://resources.example:8001",
            "user@resources.example:8001",
            "resources.example:8001/path",
            "resources.example :8001",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                journal_configuration(JournalSetup(target=target, ca_certificate=certificate))
        for pem in ("", public_ca(expired=True), certificate + "PRIVATE KEY"):
            with self.subTest(pem_length=len(pem)), self.assertRaises(ValueError):
                journal_configuration(
                    JournalSetup(target="resources.example:8001", ca_certificate=pem)
                )

    def test_matching_trust_is_idempotent_and_mismatch_never_overwrites(self) -> None:
        original = journal_configuration(
            JournalSetup(target="resources.example:8001", ca_certificate=public_ca())
        )
        changed = journal_configuration(
            JournalSetup(target="resources.example:8001", ca_certificate=public_ca())
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "journal-ca.crt"
            write_journal_trust(path, original)
            write_journal_trust(path, original)
            with self.assertRaises(ValueError):
                write_journal_trust(path, changed)
            self.assertEqual(path.read_bytes(), original.ca_certificate)
            directory = Path(folder) / "foreign-directory"
            directory.mkdir()
            with self.assertRaises(ValueError):
                write_journal_trust(directory, original)
            self.assertTrue(directory.is_dir())

    def test_existing_runtime_values_are_preserved_and_journal_values_added_once(self) -> None:
        configuration = journal_configuration(
            JournalSetup(target="resources.example:8001", ca_certificate=public_ca())
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runtime.env"
            original = b'EXISTING_FIXTURE="retain-exact-bytes"\n'
            path.write_bytes(original)
            ensure_journal_environment(path, configuration)
            first = path.read_bytes()
            ensure_journal_environment(path, configuration)
            self.assertEqual(path.read_bytes(), first)
            self.assertTrue(first.startswith(original))
            expected = "BRIAREUS_NODE_JOURNAL_TARGET=" + json.dumps(configuration.target)
            self.assertEqual(first.decode().count(expected), 1)
            self.assertIn(
                'BRIAREUS_NODE_JOURNAL_CA_FILE="/run/briareus-node/journal-ca.crt"', first.decode()
            )

    def test_existing_conflicting_runtime_target_is_not_modified(self) -> None:
        configuration = journal_configuration(
            JournalSetup(target="resources.example:8001", ca_certificate=public_ca())
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runtime.env"
            original = b'BRIAREUS_NODE_JOURNAL_TARGET="previous.example:8001"\n'
            path.write_bytes(original)
            with self.assertRaises(ValueError):
                ensure_journal_environment(path, configuration)
            self.assertEqual(path.read_bytes(), original)

    def test_nonregular_or_symlink_environment_is_rejected_before_append(self) -> None:
        configuration = journal_configuration(
            JournalSetup(target="resources.example:8001", ca_certificate=public_ca())
        )
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "retain.env"
            original = b'EXISTING_FIXTURE="must-stay-identical"\n'
            target.write_bytes(original)
            directory = Path(folder) / "directory.env"
            directory.mkdir()
            with self.assertRaises(ValueError):
                ensure_journal_environment(directory, configuration)
            link = Path(folder) / "runtime.env"
            try:
                link.symlink_to(target)
            except OSError:
                # Windows may not grant symlink creation; exercise only the
                # stat boundary, without substituting any filesystem backend.
                link.write_bytes(original)
                metadata = os.stat_result((stat.S_IFLNK | 0o777, 0, 0, 1, 0, 0, 0, 0, 0, 0))
                with (
                    patch("local.provision.os.lstat", return_value=metadata),
                    self.assertRaises(ValueError),
                ):
                    ensure_journal_environment(link, configuration)
                self.assertEqual(link.read_bytes(), original)
            else:
                with self.assertRaises(ValueError):
                    ensure_journal_environment(link, configuration)
                self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_bytes(), original)
            self.assertTrue(directory.is_dir())
