"""Generate one local adapter's runtime inputs from its real Core registration.

No credentials are printed, and no Windows/system trust store is modified.
Run using the Node project's pinned Python environment.
"""

import argparse
import ipaddress
import json
import os
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# The CLI also runs directly from local/, outside the Node container's source path.
# Resolve the existing workspace contract package without loading runtime settings.
_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "services"))
sys.path.insert(0, str(_ROOT / "shared"))
from node.local.installation_identity import InstallationIdentity  # noqa: E402 -- direct CLI source bootstrap
from node_protocol.setup import JournalSetup, NodeSetup  # noqa: E402 -- direct CLI source bootstrap


def write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
    path.chmod(0o600)


@dataclass(frozen=True, slots=True)
class JournalConfiguration:
    target: str
    ca_certificate: bytes


def journal_configuration(value: JournalSetup) -> JournalConfiguration:
    target, pem = value.target, value.ca_certificate
    parsed = urlsplit("//" + target)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or "://" in target
        or any(character.isspace() for character in target)
    ):
        raise ValueError("Explicit journal TLS host:port required")
    encoded = pem.encode()
    if not encoded or len(encoded) > 65536 or b"PRIVATE KEY" in encoded:
        raise ValueError("Bounded public journal CA bundle required")
    certificates = x509.load_pem_x509_certificates(encoded)
    now = datetime.now(UTC)
    if not certificates or any(
        not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc
        for certificate in certificates
    ):
        raise ValueError("Currently valid journal CA bundle required")
    return JournalConfiguration(target, encoded)


def write_journal_trust(path: Path, configuration: JournalConfiguration) -> None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        write_new(path, configuration.ca_certificate)
        path.chmod(0o644)
        return
    if not stat.S_ISREG(metadata.st_mode) or path.read_bytes() != configuration.ca_certificate:
        raise ValueError("Existing journal trust differs; explicit trust update required")


def ensure_journal_environment(path: Path, configuration: JournalConfiguration) -> None:
    expected = {
        "BRIAREUS_NODE_JOURNAL_TARGET": configuration.target,
        "BRIAREUS_NODE_JOURNAL_CA_FILE": "/run/briareus-node/journal-ca.crt",
    }
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        metadata = None
    if metadata is not None:
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("Existing runtime environment must be a regular file")
        lines = path.read_text().splitlines()
    else:
        lines = []
    missing = missing_environment(lines, expected)
    with path.open("ab") as stream:
        for key in expected:
            if key in missing:
                stream.write((key + "=" + json.dumps(expected[key]) + "\n").encode())


def missing_environment(lines: list[str], expected: Mapping[str, str]) -> frozenset[str]:
    missing = set(expected)
    for line in lines:
        key, separator, raw = line.partition("=")
        if separator and key in expected:
            if key not in missing or json.loads(raw) != expected[key]:
                raise ValueError("Existing journal runtime configuration differs")
            missing.remove(key)
    return frozenset(missing)


def private_rsa_key(path: Path | None) -> rsa.RSAPrivateKey:
    if path is None:
        return rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("Existing local TLS key must retain its RSA identity")
    return key


def certificate_authority(key: rsa.RSAPrivateKey, now: datetime) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Briareus local node CA")])
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), True
        )
        .sign(key, hashes.SHA256())
    )


def server_certificate(
    private: rsa.RSAPrivateKey,
    issuer: rsa.RSAPrivateKey,
    ca: x509.Certificate,
    service: str,
    names: list[x509.GeneralName],
    now: datetime,
) -> x509.Certificate:
    subject = x509.Name(
        [x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Briareus local " + service)]
    )
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca.subject)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName(names), False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(private.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer.public_key()), False
        )
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(issuer, hashes.SHA256())
    )


def new_key_file(path: Path, key: rsa.RSAPrivateKey) -> None:
    write_new(
        path,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def provision_tls(output: Path, host: ipaddress.IPv4Address, *, existing: bool) -> None:
    key = private_rsa_key(output / "ca.key" if existing else None)
    now = datetime.now(UTC)
    ca = certificate_authority(key, now)
    if not existing:
        new_key_file(output / "ca.key", key)
    (output / "ca.crt").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    alternatives: tuple[tuple[str, list[x509.GeneralName]], ...] = (
        ("node", [x509.IPAddress(ipaddress.ip_address("127.0.0.2"))]),
        (
            "registry",
            [
                x509.IPAddress(host),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"),
            ],
        ),
    )
    for service, names in alternatives:
        private = private_rsa_key(output / (service + ".key") if existing else None)
        cert = server_certificate(private, key, ca, service, names, now)
        if not existing:
            new_key_file(output / (service + ".key"), private)
        (output / (service + ".crt")).write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def require_installation(marker: Path, identity: InstallationIdentity) -> bool:
    try:
        metadata = os.lstat(marker)
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(metadata.st_mode)
        or InstallationIdentity.model_validate_json(marker.read_bytes()) != identity
    ):
        raise ValueError("Existing local installation differs; do not replace its identity")
    return True


def runtime_inputs(
    output: Path, setup: NodeSetup, host: ipaddress.IPv4Address, journal: JournalConfiguration
) -> None:
    runtime = output / "runtime.env"
    write_journal_trust(output / "journal-ca.crt", journal)
    if runtime.exists():
        ensure_journal_environment(runtime, journal)
        print("Existing runtime inputs retained; trust stores unchanged.")
        return
    values = {
        "BRIAREUS_NODE_UUID": str(setup.node_record.id),
        "BRIAREUS_NODE_RECORD": json.dumps(
            setup.node_record.model_dump(mode="json"), ensure_ascii=True
        ),
        "BRIAREUS_CORE_VERIFY_KEY": setup.core_verify_key,
        "BRIAREUS_GATEWAY_VERIFY_KEY": setup.gateway_verify_key,
        "BRIAREUS_IMAGE_REGISTRIES": json.dumps([str(host) + ":5500"]),
        "BRIAREUS_LOCAL_NODE_HOST_IP": str(host),
    }
    write_new(
        runtime,
        "".join(key + "=" + json.dumps(value) + "\n" for key, value in values.items()).encode(),
    )
    ensure_journal_environment(runtime, journal)
    print("Generated node TLS and runtime inputs; trust stores unchanged.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-ip", required=True)
    parser.add_argument("--refresh-certs", action="store_true")
    args = parser.parse_args()
    host = ipaddress.IPv4Address(args.host_ip)
    if not host.is_private or host.is_loopback:
        raise ValueError("Dedicated private WSL host interface required")
    root = Path(__file__).resolve().parents[3]
    secrets = root / ".local/briareus/secrets"
    setup = NodeSetup.model_validate_json((secrets / "node-setup.json").read_bytes())
    journal = journal_configuration(setup.journal)
    if (
        setup.endpoint != "https://127.0.0.2"
        or setup.runtime_uid != 2201
        or setup.runtime_gid != 2201
    ):
        raise ValueError("This local adapter requires its actual loopback/UID2201 registration")
    output = secrets / "node"
    output.mkdir(mode=0o700, exist_ok=True)
    marker = output / "installation.json"
    identity = InstallationIdentity(node_uuid=setup.node_record.id, registry_host=str(host))
    existing = require_installation(marker, identity)
    if not existing or args.refresh_certs:
        if not existing and list(output.iterdir()):
            raise ValueError("Refusing to overwrite unmarked local node credentials")
        provision_tls(output, host, existing=existing)
        if not existing:
            write_new(marker, identity.model_dump_json().encode())
    runtime_inputs(output, setup, host, journal)


if __name__ == "__main__":
    main()
