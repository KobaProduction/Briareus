"""Catalog-only durable lease revocation, bound to its local command executor."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import SignedOwnerProofs, VerifiedOwnerOperation, require_signed_payload
from common.owner_transactions import OwnerCommandOutcome, OwnerLocalCommandExecutor
from common.platform_errors import AccessDenied, InvalidInput
from projects._resource_persistence import CredentialLeaseRow, IntegrationRow, VariableRow
from projects.application.owner_receipts import CatalogRevokeUnusedLease
from projects.catalog.application._command_payloads import (
    RevokeCatalogLeasePayload,
)

Kind = Literal["integrations", "variables"]


class _CatalogLifecycleOperations:
    commands: OwnerLocalCommandExecutor

    @staticmethod
    def _row(kind: Kind) -> type[IntegrationRow] | type[VariableRow]:
        return IntegrationRow if kind == "integrations" else VariableRow

    async def revoke_unused_lease(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        lease_id: UUID,
        service_id: UUID,
        instance_uuid: UUID,
    ) -> OwnerCommandOutcome[CatalogRevokeUnusedLease]:
        """Fence a one-use lease *before redemption*; never reveal credential."""
        request = decision.request
        if (
            request.target_owner != "resources"
            or request.operation != "catalog.lease.revoke"
            or any(x.version != 4 for x in (lease_id, service_id, instance_uuid))
        ):
            raise InvalidInput("Catalog lease revoke requires exact origin/recipient")
        require_signed_payload(
            request,
            asdict(
                RevokeCatalogLeasePayload(
                    lease_id=str(lease_id),
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                )
            ),
        )

        async def mutation(tx: AsyncSession) -> CatalogRevokeUnusedLease:
            lease = await tx.scalar(
                select(CredentialLeaseRow)
                .where(
                    CredentialLeaseRow.id == lease_id,
                )
                .with_for_update()
            )
            if (
                lease is None
                or lease.project_id != request.project_id
                or lease.user_id != request.caller_user_id
                or lease.session_uuid != request.session_uuid
                or lease.service_id != service_id
                or lease.service_instance_uuid != instance_uuid
                or lease.redeemed_at is not None
                or lease.expires_at <= datetime.now(UTC)
            ):
                raise AccessDenied("Catalog lease already used, expired or foreign")
            lease.expires_at = datetime.now(UTC)
            return CatalogRevokeUnusedLease(
                status="revoked",
                lease_id=str(lease.id),
                resource_id=str(lease.resource_id),
                secret_returned=False,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="catalog.lease_revoked",
            target=str(lease_id),
            response_model=CatalogRevokeUnusedLease,
        )
