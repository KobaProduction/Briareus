"""Reverse-owner transactional import reservation, dispatch and reconciliation mutations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import OwnerCommandDTO
from common.platform_errors import AccessDenied, Conflict
from projects._native_import_persistence import NativeImportRow, NativeProjectRow
from projects.application.owner_receipts import (
    ReverseMarkDispatched,
    ReverseReconcileImport,
    ReverseReserveImport,
)
from projects.domain.native_import import (
    VerifiedFilesSourceReceipt,
    VerifiedNativeImportObservation,
)


async def reserve_import_record(
    tx: AsyncSession,
    request: OwnerCommandDTO,
    file: VerifiedFilesSourceReceipt,
    *,
    native_project_id: UUID,
    file_object_id: UUID,
    service_id: UUID,
    auto_analyze: bool,
    ttl_seconds: int,
    digest: str,
) -> ReverseReserveImport:
    native = await tx.scalar(
        select(NativeProjectRow).where(NativeProjectRow.id == native_project_id).with_for_update()
    )
    if (
        native is None
        or native.project_id != request.project_id
        or native.owner_service_id != service_id
        or (not native.enabled)
    ):
        raise AccessDenied("native Project current owner not active")
    pending = await tx.scalar(
        select(NativeImportRow.import_uuid)
        .where(
            NativeImportRow.project_id == request.project_id,
            NativeImportRow.native_project_id == native_project_id,
            NativeImportRow.file_object_id == file_object_id,
            NativeImportRow.source_file_version == file.file_version,
            NativeImportRow.status.in_(("reserved", "dispatched", "unknown")),
        )
        .limit(1)
    )
    if pending is not None:
        raise Conflict("native import source already has unresolved effect")
    row = NativeImportRow(
        import_uuid=uuid4(),
        operation_uuid=request.operation_uuid,
        project_id=request.project_id,
        native_project_id=native_project_id,
        file_object_id=file_object_id,
        source_file_version=file.file_version,
        source_content_sha256=file.content_sha256,
        source_size_bytes=file.size_bytes,
        auto_analyze=auto_analyze,
        actor_user_id=request.caller_user_id,
        agent_session_uuid=request.session_uuid,
        owner_service_id=service_id,
        idempotency_digest=digest,
        request_fingerprint=request.payload_sha256,
        status="reserved",
        version=1,
        cleanup_state="not_requested",
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )
    tx.add(row)
    return ReverseReserveImport(
        import_uuid=str(row.import_uuid),
        operation_uuid=str(row.operation_uuid),
        native_project_id=str(row.native_project_id),
        source_file_version=row.source_file_version,
        status="reserved",
        version=1,
    )


async def dispatch_import_record(
    tx: AsyncSession,
    request: OwnerCommandDTO,
    *,
    import_uuid: UUID,
    original_operation_uuid: UUID,
    expected_import_version: int,
    service_id: UUID,
) -> ReverseMarkDispatched:
    row = await tx.scalar(
        select(NativeImportRow).where(NativeImportRow.import_uuid == import_uuid).with_for_update()
    )
    if (
        row is None
        or row.project_id != request.project_id
        or row.agent_session_uuid != request.session_uuid
        or (row.actor_user_id != request.caller_user_id)
        or (row.owner_service_id != service_id)
        or (row.operation_uuid != original_operation_uuid)
        or (row.version != expected_import_version)
        or (row.status != "reserved")
        or (row.expires_at <= datetime.now(UTC))
    ):
        raise AccessDenied("native import intent already dispatched or revoked")
    row.status = "dispatched"
    row.dispatched_at = datetime.now(UTC)
    row.version += 1
    return ReverseMarkDispatched(
        import_uuid=str(row.import_uuid),
        status="dispatched",
        version=row.version,
        operation_uuid=str(row.operation_uuid),
    )


async def reconcile_import_record(
    tx: AsyncSession,
    request: OwnerCommandDTO,
    observed: VerifiedNativeImportObservation,
    *,
    import_uuid: UUID,
    original_operation_uuid: UUID,
    expected_import_version: int,
    service_id: UUID,
) -> ReverseReconcileImport:
    row = await tx.scalar(
        select(NativeImportRow).where(NativeImportRow.import_uuid == import_uuid).with_for_update()
    )
    if (
        row is None
        or row.project_id != request.project_id
        or row.operation_uuid != original_operation_uuid
        or (row.agent_session_uuid != request.session_uuid)
        or (row.actor_user_id != request.caller_user_id)
        or (row.owner_service_id != service_id)
        or (row.native_project_id != observed.native_project_id)
        or (row.file_object_id != observed.file_object_id)
        or (row.version != expected_import_version)
        or (row.status not in {"dispatched", "unknown"})
    ):
        raise AccessDenied("native import source, Project or CAS revision changed")
    row.status = observed.outcome
    row.version += 1
    if observed.outcome != "unknown":
        row.resolved_at = datetime.now(UTC)
        row.native_artifact_id = observed.native_artifact_id
        row.result_sha256 = observed.result_sha256
    return ReverseReconcileImport(
        import_uuid=str(row.import_uuid),
        status=row.status,
        version=row.version,
        reconciliation_required=row.status == "unknown",
    )
