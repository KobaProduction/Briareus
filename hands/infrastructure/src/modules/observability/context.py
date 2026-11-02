"""Existing provider contexts without runtime transport or environment side effects."""

from __future__ import annotations

import threading as threading

from common.account_access import AccountAccess
from infrastructure_runtime.account_clients import ObservabilityAccountClients
from modules.coolify.client import CoolifyClient as CoolifyClient
from modules.observability.application.sources import ListSources
from modules.observability.domain.sources import ProviderName, SourceInventory
from modules.observability.infrastructure.sources import AccountSourceCatalog
from modules.signoz.client import SigNozClient as SigNozClient


class ObservabilityRuntimeContext(ObservabilityAccountClients[AccountAccess]):
    def clear(self) -> None:
        with self._lock:
            self._signoz.clear()
            self._coolify.clear()

    def sources(self, provider: ProviderName | None = None) -> SourceInventory:
        return ListSources(AccountSourceCatalog(self.admin_api)).execute(provider)
