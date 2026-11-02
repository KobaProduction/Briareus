"""Bind provider identity, authenticated service effect and current membership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from authorization.domain.action_audiences import HAND_EFFECT_AUDIENCES
from authorization.domain.decisions import (
    DecisionAuthenticationRequired,
    DecisionScope,
    DecisionScopeDenied,
    VerifiedDecisionCaller,
)
from authorization.domain.project_membership import VerifiedProjectMembership
from authorization.domain.rauthy import VerifiedRauthySubject


@dataclass(frozen=True, slots=True)
class VerifiedDecisionPeer:
    consumer: Literal["gateway", "hand"]
    source_audience: str
    target_audience: str
    expires_at: datetime
    attested_effect_key: str | None = None

    def verify_scope(self, scope: DecisionScope, now: datetime) -> None:
        expected_key = scope.effect.effect_key if scope.effect is not None else None
        if self.target_audience != "briareus:access" or self.attested_effect_key != expected_key:
            raise DecisionScopeDenied("verified service audience cannot perform action")
        if self.expires_at.tzinfo is None or self.expires_at <= now:
            raise DecisionScopeDenied("verified service audience cannot perform action")
        if scope.action == "mcp.connect":
            if self.consumer != "gateway" or self.source_audience != "gateway":
                raise DecisionScopeDenied("verified service audience cannot perform action")
            return
        self._verify_hand(scope)

    def _verify_hand(self, scope: DecisionScope) -> None:
        if self.consumer != "hand" or scope.effect is None:
            raise DecisionScopeDenied("verified service audience cannot perform action")
        if self.source_audience != scope.effect.hand:
            raise DecisionScopeDenied("verified service audience cannot perform action")
        if self.source_audience not in HAND_EFFECT_AUDIENCES.get(scope.action, frozenset()):
            raise DecisionScopeDenied("verified service audience cannot perform action")


def verified_member(
    membership: VerifiedProjectMembership,
    signed: VerifiedRauthySubject,
    scope: DecisionScope,
    now: datetime,
) -> None:
    provider_matches = (
        membership.rauthy_issuer == signed.issuer and membership.rauthy_subject == signed.subject
    )
    project_matches = (
        membership.project_uuid == scope.project_uuid and membership.actor_uuid.version == 4
    )
    if not provider_matches or not project_matches:
        raise DecisionScopeDenied("no current verified Project membership")
    if membership.expires_at.tzinfo is None or membership.expires_at <= now:
        raise DecisionScopeDenied("no current verified Project membership")


def decision_caller(
    signed: VerifiedRauthySubject,
    peer: VerifiedDecisionPeer,
    membership: VerifiedProjectMembership,
    scope: DecisionScope,
    now: datetime,
) -> VerifiedDecisionCaller:
    peer.verify_scope(scope, now)
    verified_member(membership, signed, scope, now)
    expires = min(peer.expires_at, signed.expires_at, membership.expires_at)
    if expires <= now:
        raise DecisionAuthenticationRequired("trust proof expired")
    return VerifiedDecisionCaller(
        membership.actor_uuid,
        scope.project_uuid,
        scope.agent_session_uuid,
        peer.consumer,
        "rauthy",
        peer.target_audience,
        expires,
        peer.attested_effect_key,
    )
