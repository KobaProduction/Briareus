"""Atomic distributed private-peer nonce barrier with no local fallback."""

from typing import Protocol

from authorization.domain.decision_transport import ReplayNonce
from authorization.domain.decisions import DecisionAuthorityUnavailable


class PrivateValkeyNoncePort(Protocol):
    async def set(self, name: str, value: str, *, nx: bool, ex: int) -> object: ...


class ValkeyPeerReplayGuard:
    def __init__(self, *, valkey: PrivateValkeyNoncePort) -> None:
        if valkey is None:
            raise ValueError("approved distributed private Valkey transport required")
        self._valkey = valkey

    async def consume(self, *, source_audience: object, nonce: object, body_sha256: object) -> bool:
        claim = ReplayNonce.checked(source_audience, nonce, body_sha256)
        if claim is None:
            return False
        try:
            reserved = await self._valkey.set(
                claim.storage_key(),
                claim.body_sha256,
                nx=True,
                ex=30,
            )
        except Exception:
            raise DecisionAuthorityUnavailable("private peer nonce authority unavailable") from None
        if reserved is True or reserved in ("OK", b"OK"):
            return True
        if reserved is None or reserved is False:
            return False
        raise DecisionAuthorityUnavailable("private peer nonce result invalid")
