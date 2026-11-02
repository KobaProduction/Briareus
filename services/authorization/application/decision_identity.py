"""Resolve all three independent authorities before a current-grant decision."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from authorization.domain.decision_identity import VerifiedDecisionPeer, decision_caller
from authorization.domain.decisions import (
    DecisionAuthenticationRequired,
    DecisionAuthorityUnavailable,
    DecisionScope,
    DecisionScopeDenied,
    VerifiedDecisionCaller,
)
from authorization.domain.project_membership import VerifiedProjectMembership
from authorization.domain.rauthy import (
    RauthyKeysUnavailable,
    RauthyTokenRejected,
    VerifiedRauthySubject,
)


class DecisionBearerIdentity(Protocol):
    async def verify(self, bearer: str) -> VerifiedRauthySubject: ...


class DecisionPeerProof(Protocol):
    async def verify(self) -> VerifiedDecisionPeer: ...


class CurrentProjectMembershipResolver(Protocol):
    async def current_member(
        self,
        *,
        rauthy_issuer: str,
        rauthy_subject: str,
        project_uuid: UUID,
    ) -> VerifiedProjectMembership: ...


class AttestDecisionIdentity:
    def __init__(
        self,
        bearer: DecisionBearerIdentity,
        peer: DecisionPeerProof,
        membership: CurrentProjectMembershipResolver,
    ) -> None:
        self._bearer = bearer
        self._peer = peer
        self._membership = membership

    async def execute(self, bearer: str, scope: DecisionScope) -> VerifiedDecisionCaller:
        try:
            signed = await self._bearer.verify(bearer)
        except RauthyKeysUnavailable:
            raise DecisionAuthorityUnavailable("trusted issuer signing keys unavailable") from None
        except RauthyTokenRejected:
            raise DecisionAuthenticationRequired("provider bearer not verified") from None
        peer = await self._peer.verify()
        if not isinstance(peer, VerifiedDecisionPeer):
            raise DecisionScopeDenied("verified service audience cannot perform action")
        peer.verify_scope(scope, datetime.now(UTC))
        membership = await self._membership.current_member(
            rauthy_issuer=signed.issuer,
            rauthy_subject=signed.subject,
            project_uuid=scope.project_uuid,
        )
        if not isinstance(membership, VerifiedProjectMembership):
            raise DecisionScopeDenied("no current verified Project membership")
        return decision_caller(signed, peer, membership, scope, datetime.now(UTC))
