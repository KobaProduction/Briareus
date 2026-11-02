"""Owner-local quota locking and Files observation settlement mutations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import OwnerCommandDTO
from common.platform_errors import AccessDenied, Conflict
from projects._file_quota_persistence import (
    FileObjectRow,
    FileQuotaAccountRow,
    FileQuotaReservationRow,
)
from projects.application.owner_receipts import FilesConfigureQuota
from projects.domain.files_observation import VerifiedNativeFilesObservation


class _LockedReconciliation(NamedTuple):
    account: FileQuotaAccountRow
    reservation: FileQuotaReservationRow


async def lock_reservation_account(tx: AsyncSession, project_id: UUID) -> FileQuotaAccountRow:
    account = await tx.scalar(
        select(FileQuotaAccountRow)
        .where(FileQuotaAccountRow.project_id == project_id)
        .with_for_update()
    )
    if account is None or account.frozen:
        raise AccessDenied("Files quota unavailable or frozen for reconciliation")
    return account


async def require_reservation_slot(
    tx: AsyncSession, request: OwnerCommandDTO, digest: str, path_digest: str
) -> None:
    duplicate = await tx.scalar(
        select(FileQuotaReservationRow)
        .where(
            FileQuotaReservationRow.project_id == request.project_id,
            FileQuotaReservationRow.idempotency_digest == digest,
        )
        .with_for_update()
    )
    if duplicate is not None:
        if duplicate.operation_uuid != request.operation_uuid:
            raise Conflict("Files key already belongs to another operation")
        raise Conflict("Files original reservation already exists; inspect status")
    outstanding = await tx.scalar(
        select(FileQuotaReservationRow.reservation_id)
        .where(
            FileQuotaReservationRow.project_id == request.project_id,
            FileQuotaReservationRow.path_digest == path_digest,
            FileQuotaReservationRow.status.in_(("reserved", "dispatched", "unknown")),
        )
        .limit(1)
    )
    if outstanding is not None:
        raise Conflict("Files path has an unresolved write")


async def lock_file_revision(
    tx: AsyncSession, project_id: UUID, path_digest: str, expected_file_version: int
) -> FileObjectRow | None:
    existing = await tx.scalar(
        select(FileObjectRow)
        .where(FileObjectRow.project_id == project_id, FileObjectRow.path_digest == path_digest)
        .with_for_update()
    )
    current_file_version = existing.version if existing is not None else 0
    if current_file_version != expected_file_version:
        raise Conflict("Files object revision changed")
    return existing


async def lock_reconciliation_rows(
    tx: AsyncSession,
    request: OwnerCommandDTO,
    verified: VerifiedNativeFilesObservation,
    *,
    reservation_id: UUID,
    reservation_operation_uuid: UUID,
    expected_reservation_version: int,
    service_id: UUID,
) -> _LockedReconciliation:
    account = await tx.scalar(
        select(FileQuotaAccountRow)
        .where(FileQuotaAccountRow.project_id == request.project_id)
        .with_for_update()
    )
    row = await tx.scalar(
        select(FileQuotaReservationRow)
        .where(FileQuotaReservationRow.reservation_id == reservation_id)
        .with_for_update()
    )
    if (
        account is None
        or row is None
        or row.project_id != request.project_id
        or (row.agent_session_uuid != request.session_uuid)
        or (row.actor_user_id != request.caller_user_id)
        or (row.owner_service_id != service_id)
        or (row.operation_uuid != reservation_operation_uuid)
        or (row.version != expected_reservation_version)
        or (row.status not in {"dispatched", "unknown"})
        or (row.path_digest != verified.path_digest)
    ):
        raise AccessDenied("Files reservation cannot be reconciled at this revision")
    return _LockedReconciliation(account, row)


def commit_observed_write(
    tx: AsyncSession,
    request: OwnerCommandDTO,
    verified: VerifiedNativeFilesObservation,
    account: FileQuotaAccountRow,
    row: FileQuotaReservationRow,
    observed: FileObjectRow | None,
) -> None:
    if (
        verified.observed_file_version != row.expected_file_version + 1
        or verified.observed_size_bytes != row.planned_bytes
        or verified.content_sha256 != row.expected_content_sha256
        or (verified.inode_digest is None)
    ):
        raise AccessDenied("native Files write proof contradicts original intent")
    new_used = account.used_bytes - row.prior_bytes + verified.observed_size_bytes
    if new_used < 0 or new_used > account.byte_limit:
        raise Conflict("Files committed byte reconciliation violates quota")
    if observed is None:
        observed = FileObjectRow(
            id=uuid4(),
            project_id=request.project_id,
            path_digest=row.path_digest,
            version=1,
            size_bytes=verified.observed_size_bytes,
            inode_digest=verified.inode_digest,
            content_sha256=verified.content_sha256,
            deleted=False,
            confirmed_at=verified.confirmed_at,
        )
        tx.add(observed)
    else:
        observed.version = verified.observed_file_version
        observed.size_bytes = verified.observed_size_bytes
        observed.inode_digest = verified.inode_digest
        observed.content_sha256 = verified.content_sha256
        observed.deleted = False
        observed.confirmed_at = verified.confirmed_at
    account.used_bytes = new_used
    row.status = "committed"


def require_no_effect(
    verified: VerifiedNativeFilesObservation,
    row: FileQuotaReservationRow,
    observed: FileObjectRow | None,
) -> None:
    if (
        verified.outcome != "no_effect"
        or verified.observed_file_version != row.expected_file_version
        or verified.observed_size_bytes != row.prior_bytes
        or (
            observed is not None
            and (
                observed.inode_digest is None
                or verified.inode_digest != observed.inode_digest
                or verified.content_sha256 != observed.content_sha256
            )
        )
        or (
            observed is None
            and (verified.inode_digest is not None or verified.content_sha256 is not None)
        )
    ):
        raise AccessDenied("native Files no-effect evidence contradicts prior file")


async def settle_known_reconciliation(
    tx: AsyncSession,
    request: OwnerCommandDTO,
    verified: VerifiedNativeFilesObservation,
    account: FileQuotaAccountRow,
    row: FileQuotaReservationRow,
    now: datetime,
) -> None:
    observed = await tx.scalar(
        select(FileObjectRow)
        .where(
            FileObjectRow.project_id == request.project_id,
            FileObjectRow.path_digest == row.path_digest,
        )
        .with_for_update()
    )
    prior_version = observed.version if observed is not None else 0
    if prior_version != row.expected_file_version:
        raise Conflict("Files known-good file version changed during reconciliation")
    if verified.outcome == "committed":
        commit_observed_write(tx, request, verified, account, row, observed)
    else:
        require_no_effect(verified, row, observed)
        row.status = "released"
    if account.reserved_bytes < row.reserved_delta:
        raise Conflict("Files byte reservation accounting underflow")
    account.reserved_bytes -= row.reserved_delta
    row.resolved_at = now
    row.observed_file_version = verified.observed_file_version
    row.observed_size_bytes = verified.observed_size_bytes
    row.observed_inode_digest = verified.inode_digest


async def configure_quota_mutation(
    tx: AsyncSession,
    project_id: UUID,
    byte_limit: int,
    expected_quota_version: int | None,
) -> FilesConfigureQuota:
    row = await tx.scalar(
        select(FileQuotaAccountRow)
        .where(FileQuotaAccountRow.project_id == project_id)
        .with_for_update()
    )
    if row is None:
        if expected_quota_version is not None:
            raise Conflict("Files quota account does not exist at expected revision")
        row = FileQuotaAccountRow(
            project_id=project_id,
            byte_limit=byte_limit,
            used_bytes=0,
            reserved_bytes=0,
            frozen=False,
            version=1,
        )
        tx.add(row)
    else:
        if row.version != expected_quota_version:
            raise Conflict("Files quota owner revision mismatch")
        row.byte_limit = byte_limit
        if row.used_bytes + row.reserved_bytes > byte_limit:
            row.frozen = True
        row.version += 1
        row.updated_at = datetime.now(UTC)
    return FilesConfigureQuota(
        project_id=str(project_id),
        quota_version=row.version,
        byte_limit=row.byte_limit,
        frozen=row.frozen,
    )
