"""Stable typed-cache port and key scopes, independent of the Valkey adapter."""

from typing import Protocol

from pydantic import BaseModel


class CacheBackend(Protocol):
    def key(self, *parts: str) -> str: ...

    def get_model[T: BaseModel](self, key: str, model: type[T]) -> T | None: ...

    def set_model(
        self, key: str, value: BaseModel, *, ttl_seconds: int, exclude_unset: bool = False
    ) -> bool: ...

    def delete(self, *keys: str) -> bool: ...


class CacheKeys:
    def __init__(self, cache: CacheBackend) -> None:
        self.cache = cache

    def account(self, provider: str, selector: str) -> str:
        return self.cache.key("accounts", "resolved", provider, selector)

    def account_list(self, provider: str = "") -> str:
        return self.cache.key("accounts", "list", provider or "all")

    def terminal_policy(self) -> str:
        return self.cache.key("system", "runtime", "terminal")

    def mcp_policy(self) -> str:
        return self.cache.key("system", "runtime", "mcp")

    def github_policy(self) -> str:
        return self.cache.key("system", "runtime", "github")

    def gitlab_policy(self) -> str:
        return self.cache.key("system", "runtime", "gitlab")

    def browser_policy(self) -> str:
        return self.cache.key("system", "runtime", "browser")

    def admin_config(self) -> str:
        return self.cache.key("system", "admin-api", "config")

    def account_invalidation_keys(
        self,
        provider: str,
        *,
        account_id: str = "",
        alias: str = "",
    ) -> tuple[str, ...]:
        keys = [self.account_list(provider), self.account_list()]
        if account_id:
            keys.append(self.account(provider, account_id))
        if alias:
            keys.append(self.account(provider, alias))
        return tuple(dict.fromkeys(keys))
