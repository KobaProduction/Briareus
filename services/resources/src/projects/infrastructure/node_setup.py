"""Public installation inputs; transport trust never contains a Core private key."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from pydantic import field_validator

from node_protocol.setup import JournalSetup, NodeSetup


class NodeJournalSetup(JournalSetup):
    @field_validator("target")
    @classmethod
    def explicit_target(cls, value: str) -> str:
        parsed = urlsplit("//" + value)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or "://" in value
            or any(ord(character) < 33 or ord(character) > 126 for character in value)
        ):
            raise ValueError("Explicit Resources journal TLS host:port required")
        return value

    @field_validator("ca_certificate")
    @classmethod
    def public_trust(cls, value: str) -> str:
        if "PRIVATE KEY" in value:
            raise ValueError("Only public journal transport certificates may leave Core")
        certificates = x509.load_pem_x509_certificates(value.encode("ascii"))
        now = datetime.now(UTC)
        if not 1 <= len(certificates) <= 16 or any(
            not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc
            for certificate in certificates
        ):
            raise ValueError("Current public journal transport trust required")
        return "".join(
            certificate.public_bytes(Encoding.PEM).decode("ascii") for certificate in certificates
        )

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "NodeJournalSetup | None":
        target = environment.get("RESOURCES_NODE_JOURNAL_TARGET")
        ca_path = environment.get("RESOURCES_NODE_JOURNAL_CA_FILE")
        if target is None and ca_path is None:
            return None
        if not target or not ca_path:
            raise ValueError("Explicit journal target and public CA file are required together")
        with Path(ca_path).open("rb") as stream:
            public = stream.read(65537)
        if len(public) > 65536:
            raise ValueError("Bounded public journal transport trust required")
        return cls(target=target, ca_certificate=public.decode("ascii"))


class NodeSetupResult(NodeSetup):
    journal: NodeJournalSetup
