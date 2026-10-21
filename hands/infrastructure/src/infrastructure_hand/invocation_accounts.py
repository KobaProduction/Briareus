"""Per-effect account view supplied by the credential owner, never an account store."""
from __future__ import annotations
from common.account_contracts import AccountList, AccountPublic, ResolvedAccount


class InvocationAccounts:
    def __init__(self, accounts):
        self.bind(accounts)

    def bind(self, accounts):
        if not isinstance(accounts, list) or len(accounts) > 64:
            raise ValueError("Bounded current account lease required")
        self._accounts = tuple((ResolvedAccount if "credential" in item else AccountPublic).model_validate(item)
                               for item in accounts if isinstance(item, dict))
        if len(self._accounts) != len(accounts):
            raise ValueError("Current typed account metadata required")
        keys = [(item.provider, item.id) for item in self._accounts]
        if len(set(keys)) != len(keys) or any(not item.enabled for item in self._accounts):
            raise ValueError("Unique enabled current account lease required")

    def list_accounts(self, *, provider=None):
        rows = [AccountPublic.model_validate(item.model_dump(exclude={"credential"}))
                for item in self._accounts if provider is None or item.provider == provider]
        return AccountList(accounts=rows, count=len(rows))

    def resolve_account(self, selector, *, provider):
        if not isinstance(selector, str) or not selector.strip():
            raise ValueError("Explicit account selector required")
        matches = [item for item in self._accounts if item.provider == provider
                   and selector.casefold() in {item.id.casefold(), item.alias.casefold()}]
        if len(matches) != 1:
            raise ValueError("Account not present in current project credential lease")
        if not isinstance(matches[0], ResolvedAccount):
            raise ValueError("Current private credential lease required for provider effect")
        return matches[0]

    def clear(self):
        self._accounts = ()
