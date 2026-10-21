"""Read existing Platform AgentIdentity records in one currently authorised project."""
from datetime import UTC, datetime
from uuid import UUID
from sqlalchemy import select
from agents._persistence import AgentIdentityRow

def agent_payload(row):
    return {"id":str(row.id),"project_uuid":str(row.project_id),"parent_agent_id":str(row.parent_agent_id) if row.parent_agent_id else None,
        "name":row.name,"enabled":row.enabled,"created_at":row.created_at.isoformat()}

def canonical_id(value):
    from ._panel_management import ManagementError
    try:
        parsed=UUID(value)
        if parsed.version!=4 or str(parsed)!=value:raise ValueError
        return parsed
    except (ValueError,TypeError,AttributeError):raise ManagementError(422,"AGENT_IDENTIFIER_INVALID") from None

async def read_agents(service, query, actor, deadline):
    from ._panel_management import ManagementError
    data=query.data
    allowed={"project_uuid","id"} if query.action=="agents.get" else {"project_uuid","cursor","limit"}
    if set(data)-allowed or "project_uuid" not in data or query.action=="agents.get" and "id" not in data:
        raise ManagementError(422,"AGENT_QUERY_INVALID")
    project=canonical_id(data["project_uuid"])
    async def authority():
        current=await service.projection.resolve_project(issuer=query.issuer,subject=query.subject,project_uuid=project)
        if (current is None or current.user_id!=actor.user_id or current.expires_at<=datetime.now(UTC)
            or not any(item.project_id==project and "use_resources" in item.permissions for item in current.projects)):
            raise ManagementError(403,"AGENT_PROJECT_ACCESS_REQUIRED")
        return current
    await authority()
    async with service.db.transaction() as tx:
        statement=select(AgentIdentityRow).where(AgentIdentityRow.project_id==project)
        if query.action=="agents.get":
            row=await tx.scalar(statement.where(AgentIdentityRow.id==canonical_id(data["id"])))
            if row is None:raise ManagementError(404,"AGENT_NOT_FOUND")
            result={"item":agent_payload(row)}
        else:
            limit=data.get("limit",50)
            if type(limit) is not int or not 1<=limit<=100:raise ManagementError(422,"AGENT_QUERY_INVALID")
            if data.get("cursor") is not None:statement=statement.where(AgentIdentityRow.id>canonical_id(data["cursor"]))
            rows=list(await tx.scalars(statement.order_by(AgentIdentityRow.id).limit(limit+1)))
            result={"items":[agent_payload(row) for row in rows[:limit]],"has_more":len(rows)>limit,
                "next_cursor":str(rows[limit-1].id) if len(rows)>limit else None}
    await authority()
    if deadline<=datetime.now(UTC):raise ManagementError(403,"AGENT_AUTHORITY_EXPIRED")
    return result
