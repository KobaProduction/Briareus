"""Files-owned quota reservation with no Control/Identity/Access SQL joins.

Every sensitive call requires current three-owner proofs and an independently
verified private Files peer. External file effects happen OUTSIDE transactions.
Unknown dispatched writes are never automatically retried or released.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import (
    CurrentOwnerAuthorityPort,
    OwnerCommandDTO,
    OwnerProofAuthority,
    SignedOwnerProofs,
    TrustedOwnerServicePeerPort,
    VerifiedOwnerOperation,
    require_online_owner_decision,
    require_signed_payload,
)
from common.owner_transactions import OwnerCommandOutcome, OwnerLocalCommandExecutor
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from projects._file_quota_persistence import (
    FileQuotaReservationRow,
)
from projects.application.files_command_payloads import (
    FilesConfigureQuotaPayload,
    FilesDispatchPayload,
    FilesReconcileObservationPayload,
    FilesReconcileWritePayload,
    FilesReserveWritePayload,
)
from projects.application.files_observation import (
    TrustedFilesObservationPort as TrustedFilesObservationPort,
)
from projects.application.owner_receipts import (
    FilesConfigureQuota,
    FilesMarkDispatched,
    FilesReconcileWrite,
    FilesReserveWrite,
)
from projects.domain.files_observation import (
    VerifiedNativeFilesObservation as VerifiedNativeFilesObservation,
)
from projects.infrastructure._files_write_mutations import (
    configure_quota_mutation,
    lock_file_revision,
    lock_reconciliation_rows,
    lock_reservation_account,
    require_reservation_slot,
    settle_known_reconciliation,
)


class FilesOwnerSource:
    def __init__(
        self,
        db: PlatformDatabase,
        commands: OwnerLocalCommandExecutor,
        authority: OwnerProofAuthority,
        current_owners: CurrentOwnerAuthorityPort | None,
        peer_verifier: TrustedOwnerServicePeerPort | None,
        observation_verifier: TrustedFilesObservationPort | None,
        *,
        idempotency_hmac_key: bytes,
    ) -> None:
        if db.engine.url.database != "briareus_files" or commands.owner != "files":
            raise RuntimeError("Files durable authority must use its own logical database")
        if (
            current_owners is None
            or peer_verifier is None
            or observation_verifier is None
            or len(idempotency_hmac_key) < 32
        ):
            raise RuntimeError("Files source owner requires current authority, peer and HMAC")
        self.db = db
        self.commands = commands
        self.authority = authority
        self.current_owners = current_owners
        self.peer_verifier = peer_verifier
        self.observation_verifier = observation_verifier
        self._idempotency_hmac_key = idempotency_hmac_key

    async def _current(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        *,
        service_id: UUID,
        instance_uuid: UUID,
    ) -> VerifiedOwnerOperation:
        initial = self.authority.require_current(request, proofs)
        live = await require_online_owner_decision(self.authority, self.current_owners, request)
        if (
            initial.identity_epoch != live.identity_epoch
            or initial.control_epoch != live.control_epoch
            or initial.access_epoch != live.access_epoch
        ):
            raise AccessDenied("Files source owner revisions have changed")
        try:
            peer = self.peer_verifier.verify_peer(peer_evidence)
            if (
                peer.service_id != service_id
                or peer.instance_uuid != instance_uuid
                or peer.audience != "briareus:files"
                or peer.expires_at <= datetime.now(UTC)
            ):
                raise AccessDenied("Files service instance identity changed")
        except Exception:
            raise AccessDenied("trusted native Files service peer unavailable") from None
        if request.target_owner != "files":
            raise AccessDenied("Files operation addressed to foreign owner")
        return live

    async def reserve_write(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        *,
        service_id: UUID,
        instance_uuid: UUID,
        path_digest: str,
        content_sha256: str,
        planned_bytes: int,
        expected_file_version: int,
        ttl_seconds: int = 600,
    ) -> OwnerCommandOutcome[FilesReserveWrite]:
        if (
            request.operation != "files.write.reserve"
            or not 0 <= planned_bytes <= 100000000000000
            or (not expected_file_version >= 0)
            or (not 30 <= ttl_seconds <= 3600)
            or (service_id.version != 4)
            or (instance_uuid.version != 4)
            or (len(path_digest) != 64)
            or (len(content_sha256) != 64)
            or any(c not in "0123456789abcdef" for c in path_digest + content_sha256)
        ):
            raise InvalidInput("Files write reservation bounds or signed identities invalid")
        require_signed_payload(
            request,
            asdict(
                FilesReserveWritePayload(
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                    path_digest=path_digest,
                    content_sha256=content_sha256,
                    planned_bytes=planned_bytes,
                    expected_file_version=expected_file_version,
                    ttl_seconds=ttl_seconds,
                )
            ),
        )
        decision = await self._current(
            request, proofs, peer_evidence, service_id=service_id, instance_uuid=instance_uuid
        )
        digest = hmac.new(
            self._idempotency_hmac_key, request.idempotency_key.encode(), hashlib.sha256
        ).hexdigest()

        async def mutation(tx: AsyncSession) -> FilesReserveWrite:
            account = await lock_reservation_account(tx, request.project_id)
            await require_reservation_slot(tx, request, digest, path_digest)
            existing = await lock_file_revision(
                tx, request.project_id, path_digest, expected_file_version
            )
            old_bytes = (
                existing.size_bytes if existing is not None and (not existing.deleted) else 0
            )
            needed = max(0, planned_bytes - old_bytes)
            if account.used_bytes + account.reserved_bytes + needed > account.byte_limit:
                raise Conflict("Files quota would be exceeded")
            epoch_revision = hashlib.sha256(
                f"{request.project_id}:{decision.control_epoch}:{request.expected_control_revision}:{request.expected_control_resource_revision}".encode()
            ).hexdigest()
            expiry = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
            reservation = FileQuotaReservationRow(
                reservation_id=uuid4(),
                operation_uuid=request.operation_uuid,
                project_id=request.project_id,
                agent_session_uuid=request.session_uuid,
                actor_user_id=request.caller_user_id,
                owner_service_id=service_id,
                path_digest=path_digest,
                idempotency_digest=digest,
                request_fingerprint=request.payload_sha256,
                expected_content_sha256=content_sha256,
                project_access_revision=epoch_revision,
                expected_file_version=expected_file_version,
                prior_bytes=old_bytes,
                planned_bytes=planned_bytes,
                reserved_delta=needed,
                status="reserved",
                version=1,
                expires_at=expiry,
            )
            tx.add(reservation)
            account.reserved_bytes += needed
            account.version += 1
            account.updated_at = datetime.now(UTC)
            return FilesReserveWrite(
                reservation_id=str(reservation.reservation_id),
                operation_uuid=str(request.operation_uuid),
                quota_version=account.version,
                reserved_delta=needed,
                status="reserved",
                expires_at=expiry.isoformat(),
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="files.bytes_reserved",
            target=str(request.project_id),
            response_model=FilesReserveWrite,
        )

    async def mark_dispatched(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        *,
        reservation_id: UUID,
        reservation_operation_uuid: UUID,
        expected_reservation_version: int,
        service_id: UUID,
        instance_uuid: UUID,
    ) -> OwnerCommandOutcome[FilesMarkDispatched]:
        """Commit the intent BEFORE R14 may perform any filesystem effect."""
        if (
            request.operation != "files.write.dispatch"
            or reservation_id.version != 4
            or reservation_operation_uuid.version != 4
            or expected_reservation_version < 1
        ):
            raise InvalidInput("Files dispatch requires original reservation identity")
        require_signed_payload(
            request,
            asdict(
                FilesDispatchPayload(
                    reservation_id=str(reservation_id),
                    reservation_operation_uuid=str(reservation_operation_uuid),
                    expected_reservation_version=expected_reservation_version,
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                )
            ),
        )
        decision = await self._current(
            request, proofs, peer_evidence, service_id=service_id, instance_uuid=instance_uuid
        )

        async def mutation(tx: AsyncSession) -> FilesMarkDispatched:
            row = await tx.scalar(
                select(FileQuotaReservationRow)
                .where(FileQuotaReservationRow.reservation_id == reservation_id)
                .with_for_update()
            )
            if (
                row is None
                or row.project_id != request.project_id
                or row.agent_session_uuid != request.session_uuid
                or row.actor_user_id != request.caller_user_id
                or row.operation_uuid != reservation_operation_uuid
                or row.owner_service_id != service_id
                or row.version != expected_reservation_version
                or row.status != "reserved"
                or row.expires_at <= datetime.now(UTC)
            ):
                raise AccessDenied("Files original reservation is not dispatchable")
            row.status = "dispatched"
            row.dispatched_at = datetime.now(UTC)
            row.version += 1
            return FilesMarkDispatched(
                reservation_id=str(row.reservation_id),
                operation_uuid=str(row.operation_uuid),
                reservation_version=row.version,
                status="dispatched",
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="files.write_dispatched",
            target=str(reservation_id),
            response_model=FilesMarkDispatched,
        )

    async def reconcile_write(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        native_evidence: object,
        *,
        reservation_id: UUID,
        reservation_operation_uuid: UUID,
        expected_reservation_version: int,
        service_id: UUID,
        instance_uuid: UUID,
    ) -> OwnerCommandOutcome[FilesReconcileWrite]:
        """Only a signed Files OS observation may settle uncertain file effects."""
        if (
            request.operation not in {"files.write.reconcile", "files.write.finalize"}
            or reservation_id.version != 4
            or reservation_operation_uuid.version != 4
            or (expected_reservation_version < 1)
        ):
            raise InvalidInput("Files reconcile requires original stable reservation")
        decision = await self._current(
            request, proofs, peer_evidence, service_id=service_id, instance_uuid=instance_uuid
        )
        try:
            peer = self.peer_verifier.verify_peer(peer_evidence)
            verified = self.observation_verifier.verify_observation(native_evidence, peer=peer)
        except Exception:
            raise AccessDenied("native Files receipt and OS-root attestation unavailable") from None
        if not verified.matches_reconciliation(
            reservation_id=reservation_id,
            original_operation_uuid=reservation_operation_uuid,
            project_id=request.project_id,
            service_id=service_id,
            instance_uuid=instance_uuid,
        ):
            raise AccessDenied("Files observation not current or bound to original operation")
        if not verified.has_valid_optional_digests():
            raise AccessDenied("Files native evidence digest invalid")
        require_signed_payload(
            request,
            asdict(
                FilesReconcileWritePayload(
                    reservation_id=str(reservation_id),
                    reservation_operation_uuid=str(reservation_operation_uuid),
                    expected_reservation_version=expected_reservation_version,
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                    observation=FilesReconcileObservationPayload(
                        path_digest=verified.path_digest,
                        outcome=verified.outcome,
                        observed_file_version=verified.observed_file_version,
                        observed_size_bytes=verified.observed_size_bytes,
                        content_sha256=verified.content_sha256,
                        inode_digest=verified.inode_digest,
                        confirmed_at=verified.confirmed_at.isoformat(),
                    ),
                )
            ),
        )

        async def mutation(tx: AsyncSession) -> FilesReconcileWrite:
            locked = await lock_reconciliation_rows(
                tx,
                request,
                verified,
                reservation_id=reservation_id,
                reservation_operation_uuid=reservation_operation_uuid,
                expected_reservation_version=expected_reservation_version,
                service_id=service_id,
            )
            account = locked.account
            row = locked.reservation
            now = datetime.now(UTC)
            if verified.outcome == "unknown":
                row.status = "unknown"
                account.frozen = True
            else:
                await settle_known_reconciliation(tx, request, verified, account, row, now)
            row.version += 1
            account.version += 1
            account.updated_at = now
            return FilesReconcileWrite(
                reservation_id=str(row.reservation_id),
                reservation_version=row.version,
                quota_version=account.version,
                status=row.status,
                reserved_bytes=account.reserved_bytes,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="files.write_reconciled",
            target=str(reservation_id),
            response_model=FilesReconcileWrite,
        )

    async def configure_quota(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        *,
        service_id: UUID,
        instance_uuid: UUID,
        byte_limit: int,
        expected_quota_version: int | None,
    ) -> OwnerCommandOutcome[FilesConfigureQuota]:
        """Identity-superuser-authorized quota changes, no Control SQL join."""
        if (
            request.operation != "files.quota.configure"
            or not 0 <= byte_limit <= 100000000000000
            or (expected_quota_version is not None and expected_quota_version < 1)
        ):
            raise InvalidInput("Files quota policy command invalid")
        require_signed_payload(
            request,
            asdict(
                FilesConfigureQuotaPayload(
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                    byte_limit=byte_limit,
                    expected_quota_version=expected_quota_version,
                )
            ),
        )
        decision = await self._current(
            request, proofs, peer_evidence, service_id=service_id, instance_uuid=instance_uuid
        )
        if decision.actor_role != "superuser":
            raise AccessDenied("current verified Identity superuser required")

        async def mutation(tx: AsyncSession) -> FilesConfigureQuota:
            return await configure_quota_mutation(
                tx, request.project_id, byte_limit, expected_quota_version
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="files.quota_configured",
            target=str(request.project_id),
            response_model=FilesConfigureQuota,
        )
