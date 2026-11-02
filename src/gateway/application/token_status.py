"""The owning OAuth service supplies current token-family authority."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TokenStatusQuery:
    token: str = field(repr=False)
    audience: str
    client_id: str
    subject: str
    issuer: str
    expires_at: int


class TokenStatusPort(Protocol):
    async def is_active(self, query: TokenStatusQuery) -> bool: ...
