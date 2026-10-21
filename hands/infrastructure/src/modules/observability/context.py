"""Existing provider contexts without runtime transport or environment side effects."""
from __future__ import annotations
import threading
from typing import Literal
from common.admin_api_client import AdminApiClient
from common.models import JsonObject, JsonValue
from modules.coolify.client import CoolifyClient
from modules.signoz.client import SigNozClient
ProviderName = Literal["signoz", "coolify"]

class ObservabilityRuntimeContext:
    def __init__(self, admin_api: AdminApiClient) -> None:
        self.admin_api = admin_api
        self._lock = threading.Lock()
        self._signoz: dict[str, tuple[str, SigNozClient]] = {}
        self._coolify: dict[str, tuple[str, CoolifyClient]] = {}

    def sources(self, provider: ProviderName | None = None) -> JsonObject:
        if provider is not None:
            result = self.admin_api.list_accounts(provider=provider).to_json()
            return {"sources": result["accounts"], "count": result["count"]}
        signoz = self.admin_api.list_accounts(provider="signoz")
        coolify = self.admin_api.list_accounts(provider="coolify")
        sources = [*signoz.accounts, *coolify.accounts]
        return {
            "sources": [item.model_dump(mode="json") for item in sources],
            "count": len(sources),
        }

    def signoz(self, account_id: str) -> SigNozClient:
        account = self.admin_api.resolve_account(account_id, provider="signoz")
        with self._lock:
            cached = self._signoz.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = SigNozClient(account)
            self._signoz[account.id] = (account.updated_at, client)
            return client

    def coolify(self, account_id: str) -> CoolifyClient:
        account = self.admin_api.resolve_account(account_id, provider="coolify")
        with self._lock:
            cached = self._coolify.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = CoolifyClient(account)
            self._coolify[account.id] = (account.updated_at, client)
            return client


