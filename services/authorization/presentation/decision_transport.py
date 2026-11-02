"""Read only the trusted ASGI scope extension; headers never create peer proof."""

from datetime import datetime
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, ValidationError

from authorization.application.decision_transport import (
    AttestPrivateDecisionPeer,
    TrustedPeerReplayGuard,
)
from authorization.domain.decision_identity import VerifiedDecisionPeer
from authorization.domain.decision_transport import VerifiedTransportPeerRequest
from authorization.domain.decisions import (
    DecisionAuthenticationRequired,
    DecisionAuthorityUnavailable,
    DecisionScopeDenied,
)

_SCOPE_KEY = "briareus.verified_private_peer.v1"


class _TransportEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, from_attributes=True)

    transport: Literal["mtls", "unix-peer"]
    consumer: Literal["gateway", "hand"]
    source_audience: str
    target_audience: Literal["briareus:access"]
    http_body_sha256: str
    resolved_effect_key: str | None
    nonce: str
    authenticated_at: datetime
    expires_at: datetime
    verified_peer: bool


class _RequestBody:
    def __init__(self, request: Request) -> None:
        self._request = request

    async def read(self) -> bytes:
        return await self._request.body()


class TransportAuthenticatedDecisionPeerResolver:
    def __init__(self, *, replay_guard: TrustedPeerReplayGuard) -> None:
        if replay_guard is None:
            raise ValueError("real private peer replay authority is required")
        self._replay = replay_guard

    async def verify_peer(self, request: Request) -> VerifiedDecisionPeer:
        supplied = request.scope.get(_SCOPE_KEY)
        if supplied is None:
            raise DecisionAuthorityUnavailable("private peer transport unavailable")
        if not isinstance(supplied, VerifiedTransportPeerRequest):
            raise DecisionAuthenticationRequired("no independently verified private peer")
        try:
            _TransportEnvelope.model_validate(supplied)
        except ValidationError:
            raise DecisionScopeDenied("private service peer scope or freshness denied") from None
        return await AttestPrivateDecisionPeer(_RequestBody(request), self._replay).execute(
            supplied
        )
