"""Exact resource selector wire models and independently supplied owner proof."""

from __future__ import annotations

from typing import Protocol

from pydantic import model_validator

from authorization.domain.resource_scopes import CurrentResourceProof as VerifiedResourceOwnerProof
from authorization.domain.resource_scopes import HandName as HandName
from authorization.domain.resource_scopes import ResourceSelector
from authorization.domain.sessions import SessionResourceGrant
from common.platform_ids import PlatformProjectId
from runtime_peer.access_management_wire import ResourceScopeWire

__all__ = ("EffectResource", "HandName", "TrustedResourceOwnerPort", "VerifiedResourceOwnerProof")


class EffectResource(ResourceScopeWire):
    @model_validator(mode="after")
    def canonical(self) -> EffectResource:
        self.selector()
        return self

    def selector(self) -> ResourceSelector:
        return ResourceSelector(self.kind, self.id)


class TrustedResourceOwnerPort(Protocol):
    def verify_current_scope(
        self,
        *,
        project_uuid: PlatformProjectId,
        scope: SessionResourceGrant,
    ) -> VerifiedResourceOwnerProof | None:
        """Verify preobtained signed owner proof locally without storage I/O."""
        ...
