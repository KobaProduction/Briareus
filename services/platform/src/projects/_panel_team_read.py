"""Team directory read; never exposes the platform-wide user directory."""
from datetime import UTC,datetime
from sqlalchemy import select
from teams._persistence import TeamRow,TeamMembershipRow
from ._persistence import ProjectRow
from ._rauthy_user_links import RauthyUserLinkRow

async def read_team(service,query,actor,deadline):
    from ._panel_management import ManagementError,identifier
    if set(query.data)!={'id'}:
        raise ManagementError(422,'COMMAND_FIELDS_INVALID')
    team_id=identifier(query.data['id'])
    if actor.role!='operator' and not any(team.team_id==team_id and team.member for team in actor.teams):
        raise ManagementError(403,'TEAM_MEMBERSHIP_REQUIRED')
    async with service.db.transaction() as tx:
        team=await tx.get(TeamRow,team_id)
        membership=(await tx.scalars(select(TeamMembershipRow).where(TeamMembershipRow.team_id==team_id,TeamMembershipRow.user_id==actor.user_id,TeamMembershipRow.active.is_(True)))).first()
        if team is None or (actor.role!='operator' and (membership is None or not membership.active)):
            raise ManagementError(403,'TEAM_MEMBERSHIP_REQUIRED')
        members=list(await tx.scalars(select(TeamMembershipRow).where(TeamMembershipRow.team_id==team_id,TeamMembershipRow.active.is_(True)).limit(101)))
        people=list(await tx.scalars(select(RauthyUserLinkRow).where(RauthyUserLinkRow.issuer==query.issuer,RauthyUserLinkRow.user_id.in_([m.user_id for m in members[:100]]))))
        projects=list(await tx.scalars(select(ProjectRow).where(ProjectRow.owner_team_id==team_id,ProjectRow.lifecycle_status=='active').order_by(ProjectRow.name).limit(101)))
    users=[]
    for person in people:
        profile=await service.profile(query.issuer,person.subject)
        users.append({'id':str(person.user_id),'name':profile['name'],'email':profile['email'],'enabled':person.active and profile['enabled'],'role':person.briareus_role})
    if datetime.now(UTC)>=deadline:
        raise ManagementError(503,'PLATFORM_AUTHORITY_EXPIRED')
    return {'users':users,'teams':[{'id':str(team.id),'name':team.name,'owner_user_id':str(team.owner_user_id),'member_ids':[str(m.user_id) for m in members[:100]]}],
        'projects':[{'id':str(p.id),'name':p.name,'owner_user_id':None,'owner_team_id':str(team_id)} for p in projects[:100]],'truncated':len(members)>100 or len(projects)>100}
