"""Project only public audit facts; details remain in the owner database."""

from sqlalchemy import literal, select, tuple_

from common.platform_db import PlatformDatabase
from projects._control_ledger import OwnerAuditRow
from projects.application.events import PlatformEventQuery
from runtime_peer.event_projection import EventPage
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding


class SqlPlatformEventReader(_PrivateDatabaseBinding[PlatformDatabase]):
    async def read(self, query: PlatformEventQuery) -> EventPage:
        window = query.window
        statement = select(OwnerAuditRow).where(
            OwnerAuditRow.action.like("panel.%"),
            OwnerAuditRow.created_at >= window.since,
            OwnerAuditRow.created_at <= window.until,
        )
        if query.visible_entities is not None:
            statement = statement.where(OwnerAuditRow.object_id.in_(query.visible_entities))
        if window.after is not None:
            statement = statement.where(
                tuple_(OwnerAuditRow.created_at, OwnerAuditRow.id)
                > tuple_(literal(window.after[0]), literal(window.after[1])),
            )
        async with self._database.transaction() as tx:
            rows = tuple(
                await tx.scalars(
                    statement.order_by(
                        OwnerAuditRow.created_at,
                        OwnerAuditRow.id,
                    ).limit(129)
                )
            )
        return window.result(rows)
