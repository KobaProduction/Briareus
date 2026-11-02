"""Admission rules for the private disposable-browser owner."""

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from runtime_peer.domain.private_effect import PrivateEffectFacts


@dataclass(frozen=True, slots=True)
class BrowserEffectTarget:
    project_uuid: UUID
    resource_id: str
    resource_revision: int

    def require_effect(self, facts: PrivateEffectFacts, tool: str, arguments_digest: str) -> None:
        if (
            not 0 < facts.expires_at - facts.issued_at <= 20
            or facts.not_before != facts.issued_at
            or facts.project_uuid != self.project_uuid
            or facts.resource_id != self.resource_id
            or facts.resource_revision != self.resource_revision
            or tool != "browser_open"
            or facts.tool != tool
            or facts.grant_revision < 1
            or facts.arguments_digest != arguments_digest
        ):
            raise ValueError("Browser effect binding mismatch")


@dataclass(frozen=True, slots=True)
class PrivateBrowserOperation:
    operation_uuid: UUID
    fingerprint: str
    url: str
    expires_at: int

    def __post_init__(self) -> None:
        require_browser_url(self.url)

    def require_fingerprint(self, previous: str) -> None:
        if self.fingerprint != previous:
            raise ValueError("Browser operation identity reused")

    def require_output_authority(self, now: float) -> None:
        if now >= self.expires_at:
            raise ValueError("Core authority expired before browser output")


def require_browser_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(ord(character) < 33 for character in value)
    ):
        raise ValueError("Public HTTP(S) URL required")
