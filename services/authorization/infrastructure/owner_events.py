"""Read only the current Access owner's joined outbox/audit projection."""

from sqlalchemy import literal, select, tuple_

from authorization._platform_persistence import OutboxRow, SecurityAuditRow
from authorization.domain.owner_events import EventCall, EventReadActor, EventWindow, OwnerEvent
from authorization.infrastructure.journal_records import (
    AccessMutationEvent,
    AuditDetails,
    McpCallAudit,
)
from common.platform_db import PlatformDatabase
from service_runtime.platform_db_mechanics import _DatabaseBinding


def call_details(event_name: str, details: AuditDetails) -> EventCall | None:
    if not event_name.startswith("mcp.call."):
        return None
    if not isinstance(details, McpCallAudit):
        raise ValueError("MCP call audit metadata required")
    return details.call


class SqlOwnerEventRepository(_DatabaseBinding[PlatformDatabase]):
    async def read(self, actor: EventReadActor, window: EventWindow) -> tuple[OwnerEvent, ...]:
        query = (
            select(OutboxRow, SecurityAuditRow.actor_id, SecurityAuditRow.details)
            .join(
                SecurityAuditRow,
                (SecurityAuditRow.project_id == actor.project_uuid)
                & (SecurityAuditRow.action == OutboxRow.event_name)
                & (SecurityAuditRow.object_id == OutboxRow.event_payload["entity_id"].astext)
                & (
                    SecurityAuditRow.details["operation_uuid"].astext
                    == OutboxRow.event_payload["operation_uuid"].astext
                ),
            )
            .where(
                OutboxRow.event_payload["project_id"].astext == str(actor.project_uuid),
                OutboxRow.created_at >= window.since,
                OutboxRow.created_at <= window.until,
                OutboxRow.event_name.in_(
                    (
                        "session.opened",
                        "session.revoked",
                        "session.revoked_by_parent",
                        "session.elevation_requested",
                        "session.elevation_resolved",
                        "mcp.call.completed",
                        "mcp.call.failed",
                        "mcp.call.unknown",
                    )
                ),
            )
        )
        if not actor.can_read_all:
            query = query.where(SecurityAuditRow.actor_id == actor.actor_uuid)
        if window.after is not None:
            query = query.where(
                tuple_(OutboxRow.created_at, OutboxRow.id)
                > tuple_(literal(window.after.occurred_at), literal(window.after.event_uuid))
            )
        query = query.order_by(OutboxRow.created_at, OutboxRow.id).limit(129)
        async with self.database.transaction() as tx:
            rows = (await tx.execute(query)).all()
        return tuple(
            OwnerEvent(
                row.id,
                row.event_name,
                row.created_at,
                actor_uuid,
                actor.project_uuid,
                str(mutation_event(row.event_payload).operation_uuid),
                str(mutation_event(row.event_payload).entity_id),
                call_details(row.event_name, details),
            )
            for row, actor_uuid, details in rows
        )


def mutation_event(value: object) -> AccessMutationEvent:
    if not isinstance(value, AccessMutationEvent):
        raise ValueError("Joined Access mutation event required")
    return value
