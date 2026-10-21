"""Paged directory is data, separate from the bounded current-identity proof."""
from datetime import UTC, datetime
from uuid import UUID
from sqlalchemy import and_, or_, select
from teams._persistence import TeamRow, TeamMembershipRow
from ._persistence import ProjectRow

async def read_directory(service, query, actor, deadline):
    from ._panel_management import ManagementError
    data=query.data
    if set(data)-{"kind","cursor","limit"} or data.get("kind") not in {"teams","projects"}:
        raise ManagementError(422,"DIRECTORY_QUERY_INVALID")
    limit=data.get("limit",50)
    if type(limit) is not int or not 1<=limit<=100:raise ManagementError(422,"DIRECTORY_QUERY_INVALID")
    cursor=data.get("cursor")
    if cursor is not None:
        try:
            parsed=UUID(cursor)
            if parsed.version!=4 or str(parsed)!=cursor:raise ValueError
        except (ValueError,TypeError,AttributeError):raise ManagementError(422,"DIRECTORY_CURSOR_INVALID") from None
    memberships=select(TeamMembershipRow.team_id).where(TeamMembershipRow.user_id==actor.user_id,TeamMembershipRow.active.is_(True))
    async with service.db.transaction() as tx:
        if data["kind"]=="teams":
            statement=select(TeamRow,TeamMembershipRow).outerjoin(TeamMembershipRow,and_(TeamMembershipRow.team_id==TeamRow.id,
                TeamMembershipRow.user_id==actor.user_id,TeamMembershipRow.active.is_(True)))
            if actor.role!="operator":statement=statement.where(TeamRow.id.in_(memberships))
            if cursor:statement=statement.where(TeamRow.id>parsed)
            rows=list((await tx.execute(statement.order_by(TeamRow.id).limit(limit+1))).all())
            items=[{"id":str(team.id),"name":team.name,"owner":team.owner_user_id==actor.user_id,"member":member is not None} for team,member in rows[:limit]]
        else:
            statement=select(ProjectRow,TeamRow).outerjoin(TeamRow,TeamRow.id==ProjectRow.owner_team_id).where(ProjectRow.lifecycle_status=="active")
            if actor.role!="operator":statement=statement.where(or_(ProjectRow.owner_user_id==actor.user_id,ProjectRow.owner_team_id.in_(memberships)))
            if cursor:statement=statement.where(ProjectRow.id>parsed)
            rows=list((await tx.execute(statement.order_by(ProjectRow.id).limit(limit+1))).all())
            items=[]
            for project,team in rows[:limit]:
                approve=actor.role=="operator" or project.owner_user_id==actor.user_id or team is not None and team.owner_user_id==actor.user_id
                items.append({"id":str(project.id),"name":project.name,"owner":{"kind":"team" if project.owner_team_id else "user",
                    "id":str(project.owner_team_id or project.owner_user_id)},"permissions":["use_resources","approve_agent_session"] if approve else ["use_resources"]})
    fresh=await service.projection._current_link(issuer=query.issuer,subject=query.subject)
    if fresh is None or fresh.user_id!=actor.user_id or fresh.role!=actor.role or min(deadline,fresh.expires_at)<=datetime.now(UTC):
        raise ManagementError(403,"DIRECTORY_AUTHORITY_CHANGED")
    return {"kind":data["kind"],"items":items,"has_more":len(rows)>limit,"next_cursor":items[-1]["id"] if len(rows)>limit else None}
