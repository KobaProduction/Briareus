"""A current provider lease is finite, enabled, and unambiguous for its selector."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AccountIdentity:
    provider: str
    account_id: UUID
    alias: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class AccountLease:
    identities: tuple[AccountIdentity, ...]

    def __post_init__(self) -> None:
        if len(self.identities) > 64:
            raise ValueError("Bounded current account lease required")
        keys = [(item.provider, item.account_id) for item in self.identities]
        if len(set(keys)) != len(keys) or any(not item.enabled for item in self.identities):
            raise ValueError("Unique enabled current account lease required")

    def resolve(self, selector: object, provider: str) -> int:
        if not isinstance(selector, str) or not selector.strip():
            raise ValueError("Explicit account selector required")
        matches = [
            index
            for index, item in enumerate(self.identities)
            if item.provider == provider
            and selector.casefold() in {str(item.account_id).casefold(), item.alias.casefold()}
        ]
        if len(matches) != 1:
            raise ValueError("Account not present in current project credential lease")
        return matches[0]
