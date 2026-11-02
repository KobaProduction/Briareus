"""Consume a transport-authenticated request proof before granting attestation."""

from datetime import UTC, datetime
from typing import Protocol

from authorization.domain.decision_identity import VerifiedDecisionPeer
from authorization.domain.decision_transport import VerifiedTransportPeerRequest
from authorization.domain.decisions import DecisionAuthorityUnavailable, DecisionScopeDenied


class TrustedPeerReplayGuard(Protocol):
    async def consume(self, *, source_audience: str, nonce: str, body_sha256: str) -> bool: ...


class PrivateDecisionBody(Protocol):
    async def read(self) -> bytes: ...


class AttestPrivateDecisionPeer:
    def __init__(self, body: PrivateDecisionBody, replay: TrustedPeerReplayGuard) -> None:
        self._body = body
        self._replay = replay

    async def execute(self, proof: VerifiedTransportPeerRequest) -> VerifiedDecisionPeer:
        proof.verify_scope(datetime.now(UTC))
        proof.verify_body(await self._body.read())
        try:
            consumed = await self._replay.consume(
                source_audience=proof.source_audience,
                nonce=proof.nonce,
                body_sha256=proof.http_body_sha256,
            )
        except Exception:
            raise DecisionAuthorityUnavailable("peer replay authority unavailable") from None
        if consumed is not True:
            raise DecisionScopeDenied("private service proof already consumed")
        return proof.decision_peer()
