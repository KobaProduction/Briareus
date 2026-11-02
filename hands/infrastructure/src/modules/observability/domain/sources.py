"""Public source inventory cannot carry provider credentials."""

from dataclasses import dataclass
from typing import Literal

type ProviderName = Literal["signoz", "coolify"]


@dataclass(frozen=True)
class PublicSource:
    id: str
    alias: str
    provider: ProviderName
    auth_type: str
    base_url: str
    external_id: str | None
    verify_tls: bool
    ca_cert_pem: str | None
    enabled: bool
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if self.provider not in {"signoz", "coolify"}:
            raise ValueError("Infrastructure source provider required")


@dataclass(frozen=True)
class SourceInventory:
    sources: tuple[PublicSource, ...]

    @property
    def count(self) -> int:
        return len(self.sources)
