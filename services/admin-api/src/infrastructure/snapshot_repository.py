"""SQLAlchemy persistence for typed, independently refreshed administration snapshots."""

from collections.abc import Sequence
from datetime import UTC, datetime

from application.snapshot_contracts import AdminSnapshot, SnapshotContent
from domain.analysis import CoverageRequest
from domain.snapshots import CachedSnapshot, SnapshotCategory
from sqlalchemy import select

from ._adapter_resources import _SqlAlchemyRepository
from .database import CachedSnapshotRecord
from .database_spans import db_span as _db_span
from .snapshot_codec import (
    decode_coverage_request,
    decode_snapshot,
    encode_coverage_request,
    encode_snapshot,
    snapshot_category,
)


class SqlAlchemySnapshotRepository(_SqlAlchemyRepository):
    @staticmethod
    def _domain(record: CachedSnapshotRecord) -> AdminSnapshot:
        category = snapshot_category(record.category)
        return CachedSnapshot(
            key=record.key,
            category=category,
            coverage=decode_coverage_request(record.parameters_json),
            content=decode_snapshot(category, record.payload_json),
            refresh_after_seconds=record.refresh_after_seconds,
            status=record.status,
            updated_at=record.updated_at,
            attempted_at=record.attempted_at,
            error_type=record.error_type,
            error_message=record.error_message,
            created_at=record.created_at,
        )

    @_db_span("snapshots.ensure")
    async def ensure(
        self,
        key: str,
        *,
        category: SnapshotCategory,
        coverage: CoverageRequest | None = None,
        refresh_after_seconds: int,
    ) -> AdminSnapshot:
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            record = await session.get(CachedSnapshotRecord, key)
            if record is None:
                record = CachedSnapshotRecord(
                    key=key,
                    category=category,
                    parameters_json=encode_coverage_request(coverage),
                    refresh_after_seconds=refresh_after_seconds,
                    created_at=now,
                )
                session.add(record)
            else:
                record.category = category
                record.parameters_json = encode_coverage_request(coverage)
                record.refresh_after_seconds = refresh_after_seconds
            await session.flush()
            return self._domain(record)

    @_db_span("snapshots.get")
    async def get(self, key: str) -> AdminSnapshot | None:
        async with self.sessions() as session:
            record = await session.get(CachedSnapshotRecord, key)
            return self._domain(record) if record is not None else None

    @_db_span("snapshots.list_category")
    async def list_category(
        self, category: SnapshotCategory, *, limit: int = 1000
    ) -> Sequence[AdminSnapshot]:
        size = max(1, min(limit, 5000))
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(CachedSnapshotRecord)
                    .where(CachedSnapshotRecord.category == category)
                    .order_by(CachedSnapshotRecord.created_at.asc())
                    .limit(size)
                )
            ).all()
            return [self._domain(row) for row in rows]

    @_db_span("snapshots.mark_attempt")
    async def mark_attempt(self, key: str, *, status: str = "refreshing") -> None:
        async with self.sessions.begin() as session:
            record = await session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.attempted_at = datetime.now(UTC)
            record.status = status

    @_db_span("snapshots.store_success")
    async def store_success(self, key: str, content: SnapshotContent) -> AdminSnapshot:
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            record = await session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.payload_json = encode_snapshot(snapshot_category(record.category), content)
            record.status = "ready"
            record.updated_at = now
            record.attempted_at = now
            record.error_type = ""
            record.error_message = ""
            await session.flush()
            return self._domain(record)

    @_db_span("snapshots.store_error")
    async def store_error(self, key: str, exc: Exception) -> AdminSnapshot:
        now = datetime.now(UTC)
        async with self.sessions.begin() as session:
            record = await session.get(CachedSnapshotRecord, key)
            if record is None:
                raise KeyError(key)
            record.status = "error"
            record.attempted_at = now
            record.error_type = type(exc).__name__
            record.error_message = str(exc)[:4096]
            await session.flush()
            return self._domain(record)
