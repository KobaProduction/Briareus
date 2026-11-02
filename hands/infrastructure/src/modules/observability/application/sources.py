"""List only public metadata, retaining provider order and provider selection."""

from dataclasses import dataclass
from typing import Protocol

from modules.observability.domain.sources import ProviderName, PublicSource, SourceInventory


class SourceCatalog(Protocol):
    def accounts(self, provider: ProviderName) -> tuple[PublicSource, ...]: ...


@dataclass(frozen=True)
class ListSources:
    catalog: SourceCatalog

    def execute(self, provider: ProviderName | None = None) -> SourceInventory:
        if provider is not None:
            return SourceInventory(self.catalog.accounts(provider))
        return SourceInventory(
            (*self.catalog.accounts("signoz"), *self.catalog.accounts("coolify"))
        )
