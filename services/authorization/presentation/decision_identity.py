"""Adapt the private HTTP request to independent service-peer proof."""

from typing import Protocol

from fastapi import Request

from authorization.domain.decision_identity import VerifiedDecisionPeer
from authorization.domain.decisions import DecisionAuthenticationRequired


class TrustedDecisionPeerResolver(Protocol):
    async def verify_peer(self, request: Request) -> VerifiedDecisionPeer: ...


class RequestDecisionPeer:
    def __init__(self, resolver: TrustedDecisionPeerResolver, request: Request) -> None:
        self._resolver = resolver
        self._request = request

    async def verify(self) -> VerifiedDecisionPeer:
        return await self._resolver.verify_peer(self._request)


def decision_bearer(request: Request) -> str:
    if (
        len(request.headers.getlist("authorization")) != 1
        or request.headers.get("cookie") is not None
    ):
        raise DecisionAuthenticationRequired("one bearer and no browser cookie required")
    raw = request.headers.get("authorization", "")
    if not raw.startswith("Bearer ") or raw.count(" ") != 1:
        raise DecisionAuthenticationRequired("signed provider bearer required")
    return raw[7:]
