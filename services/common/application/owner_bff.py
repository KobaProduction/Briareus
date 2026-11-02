"""Read the original owner only between two fresh, matching source grants."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from common.domain.owner_authority import OwnerAuthorityUnavailable
from common.domain.owner_bff import (
    BffOwner,
    CurrentOriginalBffSourceGrant,
    OriginalBffSelector,
    OriginalOwnerStatusFact,
    StoredOriginalOwnerState,
)


class TrustedOriginalBffGrantPort(Protocol):
    async def current(
        self,
        *,
        owner: BffOwner,
        actor_user_id: UUID,
        operation_uuid: UUID,
        original_key: str,
        original_operation: str,
        scope_sha256: str,
        binding_sha256: str,
        recipient_service_id: UUID,
        recipient_instance_uuid: UUID,
        source_evidence: object,
    ) -> CurrentOriginalBffSourceGrant | None: ...


class OriginalOwnerLedger(Protocol):
    async def inspect(
        self, selector: OriginalBffSelector, project_scope: str
    ) -> StoredOriginalOwnerState: ...


@dataclass(frozen=True, slots=True)
class CurrentOriginalGrant:
    grants: TrustedOriginalBffGrantPort
    now: Callable[[], datetime]

    async def fetch(
        self, selector: OriginalBffSelector, source_evidence: object
    ) -> CurrentOriginalBffSourceGrant:
        try:
            async with asyncio.timeout(3):
                grant = await self.grants.current(
                    owner=selector.owner,
                    actor_user_id=selector.actor_user_id,
                    operation_uuid=selector.operation_uuid,
                    original_key=selector.original_key,
                    original_operation=selector.original_operation,
                    scope_sha256=selector.scope_sha256,
                    binding_sha256=selector.binding_sha256,
                    recipient_service_id=selector.recipient_service_id,
                    recipient_instance_uuid=selector.recipient_instance_uuid,
                    source_evidence=source_evidence,
                )
        except Exception:
            raise OwnerAuthorityUnavailable("owner current original scope unavailable") from None
        if not isinstance(grant, CurrentOriginalBffSourceGrant):
            raise OwnerAuthorityUnavailable("original signed owner grant changed")
        grant.require_binding(selector, self.now())
        return grant


@dataclass(frozen=True, slots=True)
class ObserveOriginalOwnerStatus:
    ledger: OriginalOwnerLedger
    grants: CurrentOriginalGrant
    now: Callable[[], datetime]

    async def execute(
        self, selector: OriginalBffSelector, source_evidence: object
    ) -> OriginalOwnerStatusFact:
        key_digest = selector.validate()
        initial = await self.grants.fetch(selector, source_evidence)
        stored = await self.ledger.inspect(selector, initial.original_project_scope)
        phase = stored.phase()
        final = await self.grants.fetch(selector, source_evidence)
        final.require_continuity(initial)
        now = self.now()
        expires = datetime.fromtimestamp(
            int(min(now + timedelta(seconds=15), final.expires_at).timestamp()), UTC
        )
        if expires <= now:
            raise OwnerAuthorityUnavailable("BFF original source signature has expired")
        return OriginalOwnerStatusFact(
            selector, key_digest, final.owner_revision, phase, now, expires
        )
