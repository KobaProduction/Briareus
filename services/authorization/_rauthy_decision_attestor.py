"""Compose trusted provider, private service-peer and current Project authorities."""

from fastapi import Request

from authorization._decision_api import DecisionCommand
from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from authorization._rauthy_jwks import RauthyJwksVerifier
from authorization.application.decision_identity import AttestDecisionIdentity
from authorization.application.decision_identity import (
    CurrentProjectMembershipResolver as CurrentProjectMembershipResolver,
)
from authorization.domain.decision_identity import VerifiedDecisionPeer as VerifiedDecisionPeer
from authorization.domain.decisions import VerifiedDecisionCaller
from authorization.infrastructure.decision_identity import RauthyDecisionBearer
from authorization.presentation.decision_identity import RequestDecisionPeer, decision_bearer
from authorization.presentation.decision_identity import (
    TrustedDecisionPeerResolver as TrustedDecisionPeerResolver,
)


class RauthyDecisionAttestor:
    def __init__(
        self,
        *,
        bearer_verifier: RauthyJwksVerifier | TrustedRauthyIssuerKeys,
        peer_resolver: TrustedDecisionPeerResolver,
        membership_resolver: CurrentProjectMembershipResolver,
    ) -> None:
        self._bearer = RauthyDecisionBearer(bearer_verifier)
        self._peer = peer_resolver
        self._membership = membership_resolver

    async def verify(self, request: Request, command: DecisionCommand) -> VerifiedDecisionCaller:
        use_case = AttestDecisionIdentity(
            self._bearer,
            RequestDecisionPeer(self._peer, request),
            self._membership,
        )
        return await use_case.execute(decision_bearer(request), command.domain_scope())
