"""Monotonic-expiry repository observations; cache entries do not confer authority."""

from dataclasses import dataclass

from source_control.providers.github.domain.repository import RepositoryMetadata


@dataclass(frozen=True, slots=True)
class CachedRepositoryMetadata:
    expires_at: float
    metadata: RepositoryMetadata

    def valid_at(self, now: float) -> bool:
        return self.expires_at > now
