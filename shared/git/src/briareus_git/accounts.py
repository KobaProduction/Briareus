"""Shared account-cache and public catalog projection; provider authority stays native."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock

from briareus_json_values import JsonObject, json_array


class AccountClientCache[T]:
    def __init__(self) -> None:
        self._lock = Lock()
        self._clients: dict[tuple[str, str], tuple[str, T]] = {}

    def get(self, scope: str, account_id: str, revision: str, factory: Callable[[], T]) -> T:
        key = (scope, account_id)
        with self._lock:
            cached = self._clients.get(key)
            if cached is not None and cached[0] == revision:
                return cached[1]
            client = factory()
            self._clients[key] = (revision, client)
            return client

    def clear(self) -> None:
        with self._lock:
            self._clients.clear()


def decorate_account(account: JsonObject, capabilities: list[str], scope: str) -> None:
    account["potential_capabilities"] = json_array(capabilities, context="potential capabilities")
    account["permission_scope"] = scope
    account["preferred_selector"] = str(account.get("alias", ""))
    account["selector_stability"] = "stable_alias"


def public_account(provider: str, base_url: str, capabilities: list[str], scope: str) -> JsonObject:
    result: JsonObject = {
        "id": "public",
        "alias": "public",
        "provider": provider,
        "auth_type": "public",
        "base_url": base_url,
        "external_id": None,
        "verify_tls": True,
        "ca_cert_pem": None,
        "enabled": True,
        "created_at": "",
        "updated_at": "",
    }
    decorate_account(result, capabilities, scope)
    return result
