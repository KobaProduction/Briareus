"""Access-owner outbox row locks, claim ownership and publisher serialization."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_persistence import OutboxRow
from authorization.domain.outbox_delivery import (
    ClaimedEvent,
    OutboxDeliveryState,
    require_outbox_limit,
)
from authorization.infrastructure.outbox_content import outbox_content_sha256
from common.platform_db import PlatformDatabase
from service_runtime.platform_db_mechanics import (
    _PrivateDatabaseBinding,
    _SessionBinding,
)


class SqlOutboxTransaction(_SessionBinding[AsyncSession]):
    async def claim(self, limit: int) -> tuple[ClaimedEvent, ...]:
        require_outbox_limit(limit)
        now = datetime.now(UTC)
        rows = await self._session.scalars(
            select(OutboxRow)
            .where(
                OutboxRow.published_at.is_(None),
                OutboxRow.locked_until.is_(None) | (OutboxRow.locked_until <= now),
            )
            .order_by(OutboxRow.created_at, OutboxRow.id)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        claimed: list[ClaimedEvent] = []
        for row in rows:
            claim_id = uuid4()
            row.claim_id = claim_id
            row.locked_until = now + timedelta(seconds=60)
            row.attempts += 1
            claimed.append(
                ClaimedEvent(
                    row.id,
                    claim_id,
                    row.event_name,
                    outbox_content_sha256(row.event_payload),
                )
            )
        return tuple(claimed)

    async def finish(self, event: ClaimedEvent, acknowledged: bool) -> bool:
        row = await self._session.scalar(
            select(OutboxRow).where(OutboxRow.id == event.event_id).with_for_update()
        )
        if row is None:
            return False
        settlement = OutboxDeliveryState(row.claim_id, row.published_at, row.attempts).settle(
            event.claim_id,
            acknowledged,
            datetime.now(UTC),
        )
        if settlement is None:
            return False
        row.published_at = settlement.published_at
        row.locked_until = settlement.locked_until
        row.claim_id = None
        return settlement.acknowledged


class SqlOutboxTransactions(_PrivateDatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def open(self) -> AsyncIterator[SqlOutboxTransaction]:
        async with self._database.transaction() as session:
            yield SqlOutboxTransaction(session)
