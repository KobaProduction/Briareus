"""Private Platform transport and exact membership wire serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from authorization.application.project_membership import (
    ResolveCurrentProjectMembership,
    VerifiedPlatformMembershipDelegation,
)
from authorization.domain.decisions import DecisionAuthorityUnavailable, DecisionScopeDenied
from authorization.domain.project_membership import MembershipSelector, VerifiedProjectMembership
from authorization.infrastructure.authority_json import load_authority_json
from service_runtime._reference_bindings import _PeerBinding


@dataclass(frozen=True, slots=True)
class VerifiedPlatformMembershipResponse:
    status_code: int
    content_type: str
    body: bytes


class TrustedPlatformDecisionPeer(Protocol):
    async def signed_member_delegation(
        self,
        *,
        issuer: str,
        subject: str,
        project_uuid: UUID,
    ) -> VerifiedPlatformMembershipDelegation: ...

    async def query_project_member(
        self,
        *,
        bearer: SecretStr,
        body: bytes,
    ) -> VerifiedPlatformMembershipResponse: ...


class _DelegationEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, from_attributes=True)

    bearer: SecretStr
    issuer: str
    subject: str
    project_uuid: UUID
    audience: Literal["briareus:platform"]
    expires_at: datetime


class _CurrentMember(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer: str
    subject: str
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime

    def domain(self) -> VerifiedProjectMembership:
        return VerifiedProjectMembership(
            self.issuer,
            self.subject,
            self.actor_uuid,
            self.project_uuid,
            self.expires_at,
        )


class PlatformMembershipPeerAdapter(_PeerBinding[TrustedPlatformDecisionPeer]):
    async def delegate(self, selector: MembershipSelector) -> VerifiedPlatformMembershipDelegation:
        try:
            delegation = await self._peer.signed_member_delegation(
                issuer=selector.issuer,
                subject=selector.subject,
                project_uuid=selector.project_uuid,
            )
        except Exception:
            raise DecisionAuthorityUnavailable("Platform service delegation unavailable") from None
        if not isinstance(delegation, VerifiedPlatformMembershipDelegation):
            raise DecisionScopeDenied("Platform delegated subject/project proof invalid")
        try:
            _DelegationEnvelope.model_validate(delegation)
        except ValidationError:
            raise DecisionScopeDenied("Platform delegated subject/project proof invalid") from None
        return delegation

    async def member(
        self,
        selector: MembershipSelector,
        delegation: VerifiedPlatformMembershipDelegation,
    ) -> VerifiedProjectMembership:
        body = json.dumps(
            {
                "issuer": selector.issuer,
                "subject": selector.subject,
                "project_uuid": str(selector.project_uuid),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        if len(body) > 4096:
            raise DecisionScopeDenied("Platform selector exceeds maximum")
        try:
            response = await self._peer.query_project_member(bearer=delegation.bearer, body=body)
        except Exception:
            raise DecisionAuthorityUnavailable(
                "private Platform owner request unavailable"
            ) from None
        return _verified_response(response)


def _verified_response(response: VerifiedPlatformMembershipResponse) -> VerifiedProjectMembership:
    if not isinstance(response, VerifiedPlatformMembershipResponse):
        raise DecisionAuthorityUnavailable("unverified Platform transport response")
    if response.status_code == 403:
        raise DecisionScopeDenied("current Project membership denied")
    if response.status_code != 200 or response.content_type.split(";", 1)[0] != "application/json":
        raise DecisionAuthorityUnavailable("current Platform membership proof unavailable")
    payload = _bounded_member_body(response.body)
    try:
        return _CurrentMember.model_validate(load_authority_json(payload)).domain()
    except ValueError:
        raise DecisionAuthorityUnavailable("Platform owner response invalid") from None


def _bounded_member_body(body: object) -> bytes:
    if not isinstance(body, bytes) or not 1 <= len(body) <= 4096:
        raise DecisionAuthorityUnavailable("current Platform membership proof unavailable")
    return body


class PlatformCurrentProjectResolver:
    def __init__(self, *, trusted_peer: TrustedPlatformDecisionPeer) -> None:
        if trusted_peer is None:
            raise ValueError("trusted Platform decision peer is required")
        self._use_case = ResolveCurrentProjectMembership(
            PlatformMembershipPeerAdapter(trusted_peer)
        )

    async def current_member(
        self,
        *,
        rauthy_issuer: str,
        rauthy_subject: str,
        project_uuid: UUID,
    ) -> VerifiedProjectMembership:
        selector = MembershipSelector.checked(rauthy_issuer, rauthy_subject, project_uuid)
        return await self._use_case.execute(selector)
