"""Reverse/Native owner import ledger; immutable Files refs, no cross-DB FK.

Native Ghidra/OS artifacts and source File bytes belong to OTHER owners and
must be verified via signed private ports before any import is dispatched.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

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
from common.platform_errors import AccessDenied, InvalidInput
from projects.application.native_import import TrustedFilesSourcePort as TrustedFilesSourcePort
from projects.application.native_import import (
    TrustedNativeImportObserver as TrustedNativeImportObserver,
)
from projects.application.owner_receipts import (
    ReverseMarkDispatched,
    ReverseReconcileImport,
    ReverseReserveImport,
)
from projects.application.reverse_payloads import (
    DispatchNativeImportPayload,
    NativeImportObservationPayload,
    ReconcileNativeImportPayload,
    ReserveNativeImportPayload,
)
from projects.domain.native_import import VerifiedFilesSourceReceipt as VerifiedFilesSourceReceipt
from projects.domain.native_import import (
    VerifiedNativeImportObservation as VerifiedNativeImportObservation,
)
from projects.infrastructure._native_import_mutations import (
    dispatch_import_record,
    reconcile_import_record,
    reserve_import_record,
)


class ReverseOwnerSource:
    def __init__(
        self,
        db: PlatformDatabase,
        commands: OwnerLocalCommandExecutor,
        authority: OwnerProofAuthority,
        current_owners: CurrentOwnerAuthorityPort | None,
        peer_verifier: TrustedOwnerServicePeerPort | None,
        files_source: TrustedFilesSourcePort | None,
        native_observer: TrustedNativeImportObserver | None,
        *,
        idempotency_hmac_key: bytes,
    ) -> None:
        if db.engine.url.database != "briareus_reverse" or commands.owner != "reverse":
            raise RuntimeError("native imports require only the Reverse owner DB")
        if (
            current_owners is None
            or peer_verifier is None
            or files_source is None
            or (native_observer is None)
            or (len(idempotency_hmac_key) < 32)
        ):
            raise RuntimeError("native import needs current authorities and Files provenance")
        self.db = db
        self.commands = commands
        self.authority = authority
        self.current_owners = current_owners
        self.peer_verifier = peer_verifier
        self.files_source = files_source
        self.native_observer = native_observer
        self._key = idempotency_hmac_key

    async def _current(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        *,
        service_id: UUID,
        instance_uuid: UUID,
    ) -> VerifiedOwnerOperation:
        first = self.authority.require_current(request, proofs)
        live = await require_online_owner_decision(self.authority, self.current_owners, request)
        if (
            first.identity_epoch != live.identity_epoch
            or first.control_epoch != live.control_epoch
            or first.access_epoch != live.access_epoch
        ):
            raise AccessDenied("native owner permission epoch revoked")
        try:
            peer = self.peer_verifier.verify_peer(peer_evidence)
            if (
                peer.service_id != service_id
                or peer.instance_uuid != instance_uuid
                or peer.audience != "briareus:reverse"
                or (peer.expires_at <= datetime.now(UTC))
            ):
                raise AccessDenied("native service instance identity mismatch")
        except Exception:
            raise AccessDenied("trusted native service peer missing") from None
        if request.target_owner != "reverse":
            raise AccessDenied("native operation addressed to foreign DB owner")
        return live

    async def reserve_import(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        files_evidence: object,
        *,
        native_project_id: UUID,
        file_object_id: UUID,
        service_id: UUID,
        instance_uuid: UUID,
        auto_analyze: bool,
        ttl_seconds: int = 900,
    ) -> OwnerCommandOutcome[ReverseReserveImport]:
        if (
            request.operation not in {"reverse.import.reserve", "reverse.import.claim"}
            or native_project_id.version != 4
            or file_object_id.version != 4
            or (not 60 <= ttl_seconds <= 3600)
        ):
            raise InvalidInput("invalid signed native import selection")
        decision = await self._current(
            request, proofs, peer_evidence, service_id=service_id, instance_uuid=instance_uuid
        )
        try:
            file = self.files_source.verify_current_file(
                files_evidence, project_id=request.project_id, file_object_id=file_object_id
            )
        except Exception:
            raise AccessDenied("current signed Files version unavailable") from None
        if not file.matches_source(project_id=request.project_id, file_object_id=file_object_id):
            raise AccessDenied("Files source owner provenance mismatch")
        require_signed_payload(
            request,
            asdict(
                ReserveNativeImportPayload(
                    native_project_id=str(native_project_id),
                    file_object_id=str(file_object_id),
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                    auto_analyze=auto_analyze,
                    ttl_seconds=ttl_seconds,
                    file_version=file.file_version,
                    content_sha256=file.content_sha256,
                    size_bytes=file.size_bytes,
                    source_revision=file.source_revision,
                )
            ),
        )
        digest = hmac.new(self._key, request.idempotency_key.encode(), hashlib.sha256).hexdigest()

        async def mutation(tx: AsyncSession) -> ReverseReserveImport:
            return await reserve_import_record(
                tx,
                request,
                file,
                native_project_id=native_project_id,
                file_object_id=file_object_id,
                service_id=service_id,
                auto_analyze=auto_analyze,
                ttl_seconds=ttl_seconds,
                digest=digest,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="reverse.import_reserved",
            target=str(native_project_id),
            response_model=ReverseReserveImport,
        )

    async def mark_dispatched(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        *,
        import_uuid: UUID,
        original_operation_uuid: UUID,
        expected_import_version: int,
        service_id: UUID,
        instance_uuid: UUID,
    ) -> OwnerCommandOutcome[ReverseMarkDispatched]:
        """Commit dispatch intent before invoking external Ghidra/OS import."""
        if (
            request.operation != "reverse.import.dispatch"
            or import_uuid.version != 4
            or original_operation_uuid.version != 4
            or (expected_import_version < 1)
        ):
            raise InvalidInput("native import dispatch requires original CAS revision")
        require_signed_payload(
            request,
            asdict(
                DispatchNativeImportPayload(
                    import_uuid=str(import_uuid),
                    original_operation_uuid=str(original_operation_uuid),
                    expected_import_version=expected_import_version,
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                )
            ),
        )
        decision = await self._current(
            request, proofs, peer_evidence, service_id=service_id, instance_uuid=instance_uuid
        )

        async def mutation(tx: AsyncSession) -> ReverseMarkDispatched:
            return await dispatch_import_record(
                tx,
                request,
                import_uuid=import_uuid,
                original_operation_uuid=original_operation_uuid,
                expected_import_version=expected_import_version,
                service_id=service_id,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="reverse.import_dispatched",
            target=str(import_uuid),
            response_model=ReverseMarkDispatched,
        )

    async def reconcile_import(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        peer_evidence: object,
        native_evidence: object,
        *,
        import_uuid: UUID,
        original_operation_uuid: UUID,
        expected_import_version: int,
        service_id: UUID,
        instance_uuid: UUID,
    ) -> OwnerCommandOutcome[ReverseReconcileImport]:
        """Only verified native effect/absence receipt settles dispatched import."""
        if (
            request.operation != "reverse.import.reconcile"
            or import_uuid.version != 4
            or original_operation_uuid.version != 4
            or (expected_import_version < 1)
        ):
            raise InvalidInput("native import reconciliation requires original CAS revision")
        decision = await self._current(
            request, proofs, peer_evidence, service_id=service_id, instance_uuid=instance_uuid
        )
        try:
            peer = self.peer_verifier.verify_peer(peer_evidence)
            observed = self.native_observer.verify_native_effect(native_evidence, peer=peer)
        except Exception:
            raise AccessDenied("native Ghidra/OS import provenance unavailable") from None
        if not observed.matches_import(
            import_uuid=import_uuid,
            original_operation_uuid=original_operation_uuid,
            project_id=request.project_id,
            service_id=service_id,
        ):
            raise AccessDenied("native observation not scoped to original import")
        if observed.outcome == "succeeded":
            if not observed.has_valid_result_identity():
                raise AccessDenied("signed native success has no valid result identity")
        elif observed.native_artifact_id is not None or observed.result_sha256 is not None:
            raise AccessDenied("unconfirmed import cannot claim a native result artifact")
        require_signed_payload(
            request,
            asdict(
                ReconcileNativeImportPayload(
                    import_uuid=str(import_uuid),
                    original_operation_uuid=str(original_operation_uuid),
                    expected_import_version=expected_import_version,
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                    native_observation=NativeImportObservationPayload(
                        native_project_id=str(observed.native_project_id),
                        file_object_id=str(observed.file_object_id),
                        outcome=observed.outcome,
                        native_artifact_id=observed.native_artifact_id,
                        result_sha256=observed.result_sha256,
                        observed_at=observed.observed_at.isoformat(),
                        native_scope_digest=observed.native_scope_digest,
                    ),
                )
            ),
        )

        async def mutation(tx: AsyncSession) -> ReverseReconcileImport:
            return await reconcile_import_record(
                tx,
                request,
                observed,
                import_uuid=import_uuid,
                original_operation_uuid=original_operation_uuid,
                expected_import_version=expected_import_version,
                service_id=service_id,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="reverse.import_reconciled",
            target=str(import_uuid),
            response_model=ReverseReconcileImport,
        )
