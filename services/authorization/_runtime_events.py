"""Read committed Access signals through the existing authenticated owner peer.

This is a separate read projection, not an acknowledgement of the owner's
durable outbox. Overlapping windows cover concurrent transaction commits;
stable outbox IDs let consumers remove duplicates across workers/reconnects.
"""
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, tuple_

from authorization._platform_persistence import OutboxRow, SecurityAuditRow
from common.platform_errors import AccessDenied, InvalidInput


async def read_events(database, actor, command):
    if set(command) - {"since", "until", "after"} or not {"since", "until"} <= set(command):
        raise InvalidInput("Exact event window required")
    now = datetime.now(UTC)
    since = datetime.fromisoformat(command["since"])
    until = datetime.fromisoformat(command["until"])
    if (since.tzinfo is None or until.tzinfo is None or since > until
        or until > now + timedelta(seconds=5)):
        raise InvalidInput("Invalid event window")
    floor = now - timedelta(hours=24)
    truncated = since < floor
    since = max(since, floor)
    query = select(OutboxRow, SecurityAuditRow.actor_id, SecurityAuditRow.details).join(SecurityAuditRow,
        (SecurityAuditRow.project_id == actor.project_uuid)
        & (SecurityAuditRow.action == OutboxRow.event_name)
        & (SecurityAuditRow.object_id == OutboxRow.event_payload["entity_id"].astext)
        & (SecurityAuditRow.details["operation_uuid"].astext
           == OutboxRow.event_payload["operation_uuid"].astext)
    ).where(
        OutboxRow.event_payload["project_id"].astext == str(actor.project_uuid),
        OutboxRow.created_at >= since, OutboxRow.created_at <= until,
        OutboxRow.event_name.in_(("session.opened", "session.revoked", "session.revoked_by_parent",
            "session.elevation_requested", "session.elevation_resolved",
            "mcp.call.completed", "mcp.call.failed", "mcp.call.unknown")),
    )
    if "approve_agent_session" not in actor.permissions:
        query = query.where(SecurityAuditRow.actor_id == actor.actor_uuid)
    after = command.get("after")
    if after is not None:
        if not isinstance(after, list) or len(after) != 2:
            raise InvalidInput("Invalid event cursor")
        instant, identifier = datetime.fromisoformat(after[0]), UUID(after[1])
        if instant.tzinfo is None or not since <= instant <= until:
            raise InvalidInput("Invalid event cursor")
        query = query.where(tuple_(OutboxRow.created_at, OutboxRow.id) > tuple_(instant, identifier))
    query = query.order_by(OutboxRow.created_at, OutboxRow.id).limit(129)
    async with database.transaction() as tx:
        rows = list((await tx.execute(query)).all())
    if actor.expires_at <= datetime.now(UTC):
        raise AccessDenied("Event reader authority expired")
    items = [{"event_id": str(row.id), "type": row.event_name,
        "occurredAt": row.created_at.isoformat(), "actor_id": str(actor_id),
        "project_id": str(actor.project_uuid),
        "operation_id": row.event_payload["operation_uuid"],
        "entity_id": row.event_payload["entity_id"],
        **({"call": details["call"]} if row.event_name.startswith("mcp.call.") else {})}
        for row, actor_id, details in rows[:128]]
    last = rows[127][0] if len(rows) > 128 else None
    return {"items": items, "truncated": truncated,
        "next": [last.created_at.isoformat(), str(last.id)] if last else None}
