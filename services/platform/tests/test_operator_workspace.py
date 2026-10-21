"""Operator visibility is an owner decision; ordinary membership stays bounded."""
import unittest
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC,datetime,timedelta
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from projects._oidc_membership_projection import PlatformOidcMembershipProjection,CurrentRauthyUserLink,PlatformSubjectLinkUnavailable
from projects._persistence import ProjectRow
from projects._rauthy_user_links import RauthyUserLinkRow
from projects._panel_management import PlatformAdministration,ManagementQuery,ManagementError
from teams._persistence import TeamRow,TeamMembershipRow

_ISSUER,_SUBJECT='https://identity.example','fixture'

class UserLinkFixture:
    def __init__(self,actor):
        self.current=CurrentRauthyUserLink(_ISSUER,_SUBJECT,actor,True,'user',1,datetime.now(UTC)+timedelta(seconds=25))
    async def current_link(self,**kwargs):
        return self.current

class SQLiteOwnerFixture:
    def __init__(self):
        self.engine=SimpleNamespace(url=SimpleNamespace(database='briareus_platform'))
        self.sql=create_engine('sqlite://',execution_options={'schema_translate_map':{'teams':None,'projects':None,'control':None,'agents':None}})
        for table in (TeamRow.__table__,TeamMembershipRow.__table__,ProjectRow.__table__,RauthyUserLinkRow.__table__):
            table.create(self.sql)
    @asynccontextmanager
    async def transaction(self):
        with Session(self.sql,expire_on_commit=False) as session,session.begin():
            class Query:
                async def get(self,model,key):return session.get(model,key)
                async def execute(self,statement,params=None):
                    if 'pg_advisory_xact_lock' not in str(statement):return session.execute(statement,params)
                async def scalar(self,statement):return session.scalar(statement)
                async def scalars(self,statement):return session.scalars(statement)
                def add(self,row):session.add(row)
                async def flush(self):session.flush()
            yield Query()


class OperatorWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.actor,self.other,self.team,self.project,self.personal=uuid4(),uuid4(),uuid4(),uuid4(),uuid4()
        self.db=SQLiteOwnerFixture()
        self.links=UserLinkFixture(self.actor)
        self.source=PlatformOidcMembershipProjection(database=self.db,subject_links=self.links)
        with Session(self.db.sql) as session,session.begin():
            session.add(TeamRow(id=self.team,name="Other team",owner_user_id=self.other))
            session.add(ProjectRow(id=self.project,name="Team project",owner_team_id=self.team))
            session.add(ProjectRow(id=self.personal,name="Other personal",owner_user_id=self.other))

    def tearDown(self):
        self.db.sql.dispose()

    async def test_large_operator_directory_keeps_identity_and_pages_all_projects(self):
        self.links.current=replace(self.links.current,role="operator")
        with Session(self.db.sql) as session,session.begin():
            for index in range(105):
                session.add(ProjectRow(id=uuid4(),name="Project "+str(index),owner_user_id=self.actor))
        current=await self.source.resolve(issuer=_ISSUER,subject=_SUBJECT)
        self.assertTrue(current.directory_paged)
        self.assertEqual(current.projects,())
        self.assertIsNotNone(await self.source.resolve_project(issuer=_ISSUER,subject=_SUBJECT,project_uuid=self.project))
        from projects._panel_directory import read_directory
        service=SimpleNamespace(db=self.db,projection=self.source)
        cursor=None;found=set()
        while True:
            reply=await read_directory(service,ManagementQuery(issuer=_ISSUER,subject=_SUBJECT,
                operation_uuid=uuid4(),action="directory",data={"kind":"projects","limit":25,"cursor":cursor}),
                current,datetime.now(UTC)+timedelta(seconds=20))
            found.update(row["id"] for row in reply["items"])
            if not reply["has_more"]:break
            self.assertIsNotNone(reply["next_cursor"])
            cursor=reply["next_cursor"]
        self.assertEqual(len(found),107)

    async def test_agent_directory_is_project_scoped_and_paged(self):
        from agents._persistence import AgentIdentityRow
        from projects._panel_agents import read_agents
        AgentIdentityRow.__table__.create(self.db.sql)
        own=uuid4();first=uuid4();second=uuid4();foreign=uuid4()
        with Session(self.db.sql) as session,session.begin():
            session.add(ProjectRow(id=own,name="Owned",owner_user_id=self.actor))
            session.add_all([AgentIdentityRow(id=first,project_id=own,name="First"),
                AgentIdentityRow(id=second,project_id=own,name="Second"),
                AgentIdentityRow(id=foreign,project_id=self.personal,name="Foreign")])
        actor=await self.source.resolve(issuer=_ISSUER,subject=_SUBJECT)
        service=SimpleNamespace(db=self.db,projection=self.source)
        async def call(action,data):
            return await read_agents(service,ManagementQuery(issuer=_ISSUER,subject=_SUBJECT,operation_uuid=uuid4(),action=action,data=data),
                actor,datetime.now(UTC)+timedelta(seconds=20))
        page=await call("agents.list",{"project_uuid":str(own),"limit":1})
        self.assertTrue(page["has_more"])
        next_page=await call("agents.list",{"project_uuid":str(own),"limit":1,"cursor":page["next_cursor"]})
        self.assertEqual({row["id"] for row in page["items"]+next_page["items"]},{str(first),str(second)})
        with self.assertRaises(ManagementError) as caught:
            await call("agents.get",{"project_uuid":str(own),"id":str(foreign)})
        self.assertEqual(caught.exception.status,404)
        with self.assertRaises(ManagementError) as caught:
            await call("agents.list",{"project_uuid":str(self.personal)})
        self.assertEqual(caught.exception.status,403)

    async def test_regular_user_cannot_list_or_resolve_foreign_projects(self):
        result=await self.source.resolve(issuer=_ISSUER,subject=_SUBJECT)
        self.assertEqual(result.teams,())
        self.assertEqual(result.projects,())
        for project in (self.project,self.personal):
            self.assertIsNone(await self.source.resolve_project(issuer=_ISSUER,subject=_SUBJECT,project_uuid=project))

    async def test_operator_sees_real_owners_without_becoming_a_member(self):
        self.links.current=replace(self.links.current,role="operator")
        result=await self.source.resolve(issuer=_ISSUER,subject=_SUBJECT)
        self.assertEqual({p.project_id for p in result.projects},{self.project,self.personal})
        self.assertFalse(result.teams[0].member)
        self.assertFalse(result.teams[0].owner)
        personal=next(p for p in result.projects if p.project_id==self.personal)
        self.assertEqual(personal.owner_id,self.other)
        for project in (self.project,self.personal):
            exact=await self.source.resolve_project(issuer=_ISSUER,subject=_SUBJECT,project_uuid=project)
            self.assertEqual(len(exact.projects),1)
            self.assertIn("use_resources",exact.projects[0].permissions)
        self.links.current=replace(self.links.current,role="user")
        self.assertIsNone(await self.source.resolve_project(issuer=_ISSUER,subject=_SUBJECT,project_uuid=self.project))

    async def test_member_directory_is_team_scoped_and_never_unlocks_global_administration(self):
        async def profile(issuer,subject):return {'name':subject,'email':subject+'@example.invalid','enabled':True}
        service=SimpleNamespace(db=self.db,projection=self.source,profile=profile)
        deadline=datetime.now(UTC)+timedelta(seconds=20)
        query=ManagementQuery(issuer=_ISSUER,subject=_SUBJECT,operation_uuid=uuid4(),action='team.read',data={'id':str(self.team)})
        with self.assertRaises(ManagementError):
            await PlatformAdministration.execute(service,query,deadline)
        with Session(self.db.sql) as session,session.begin():
            session.add(TeamMembershipRow(team_id=self.team,user_id=self.actor,active=True))
            for actor,subject in ((self.actor,'member'),(uuid4(),'unrelated')):
                session.add(RauthyUserLinkRow(user_id=actor,issuer=_ISSUER,subject=subject,briareus_role='user',active=True,version=1,created_at=datetime.now(UTC),updated_at=datetime.now(UTC)))
        result=await PlatformAdministration.execute(service,query,deadline)
        self.assertEqual([person['id'] for person in result['users']],[str(self.actor)])
        self.assertEqual([project['id'] for project in result['projects']],[str(self.project)])
        self.assertEqual([team['id'] for team in result['teams']],[str(self.team)])
        with self.assertRaises(ManagementError):
            await PlatformAdministration.execute(service,query.model_copy(update={'action':'inventory','data':{}}),deadline)

    async def test_only_operator_grants_inviter_and_team_ownership_does_not_imply_it(self):
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.ext.compiler import compiles
        from unittest.mock import patch
        from projects._control_ledger import OwnerAuditRow, OwnerOutboxRow
        @compiles(JSONB, 'sqlite')
        def sqlite_json(type_, compiler, **kwargs): return 'JSON'
        for table in (OwnerAuditRow.__table__, OwnerOutboxRow.__table__): table.create(self.db.sql)
        now=datetime.now(UTC)
        for user_id,subject,role in ((self.actor,'admin','operator'),(self.other,'member','user')):
            with Session(self.db.sql) as session,session.begin():
                session.add(RauthyUserLinkRow(user_id=user_id,issuer=_ISSUER,subject=subject,
                    briareus_role=role,active=True,version=1,created_at=now,updated_at=now))
        @asynccontextmanager
        async def transaction():
            with Session(self.db.sql,expire_on_commit=False) as session,session.begin():
                class Tx:
                    async def get(self,model,key,**kwargs): return session.get(model,key)
                    async def scalar(self,query): return session.scalar(query)
                    async def scalars(self,query): return session.scalars(query)
                    async def execute(self,query,params=None):
                        if 'pg_advisory_xact_lock' not in str(query): return session.execute(query,params)
                    def add(self,row): session.add(row)
                    async def flush(self): session.flush()
                yield Tx()
        async def resolve(**query):
            admin=query['subject']=='admin'
            return SimpleNamespace(user_id=self.actor if admin else self.other,role='operator' if admin else 'user',
                expires_at=now+timedelta(seconds=25),teams=(SimpleNamespace(owner=True),))
        service=SimpleNamespace(db=SimpleNamespace(transaction=transaction),projection=SimpleNamespace(resolve=resolve))
        async def command(subject,action,data,operation=None):
            query=ManagementQuery(issuer=_ISSUER,subject=subject,operation_uuid=operation or uuid4(),action=action,data=data)
            return await PlatformAdministration.execute(service,query,now+timedelta(seconds=20))
        with patch.dict('os.environ',{'RAUTHY_INVITATION_EMAIL_READY':'0'}):
            self.assertFalse((await command('member','invitation.capabilities',{}))['can_invite'])
            for action,data in [('invitation.issue',{'email':'fixture@example.invalid'}),('inviter.set',{'user_id':str(self.other),'enabled':True})]:
                with self.assertRaises(ManagementError) as denied: await command('member',action,data)
                self.assertEqual(denied.exception.status,403)
            operation=uuid4()
            result=await command('admin','inviter.set',{'user_id':str(self.other),'enabled':True},operation)
            self.assertEqual(await command('admin','inviter.set',{'user_id':str(self.other),'enabled':True},operation),result)
            self.assertTrue((await command('member','invitation.capabilities',{}))['can_invite'])
            with self.assertRaises(ManagementError) as mail: await command('member','invitation.issue',{'email':'fixture@example.invalid'})
            self.assertEqual(mail.exception.code,'RAUTHY_INVITATION_MAIL_UNCONFIGURED')
            await command('admin','inviter.set',{'user_id':str(self.other),'enabled':False})
            self.assertFalse((await command('member','invitation.capabilities',{}))['can_invite'])
            with Session(self.db.sql) as session:
                self.assertEqual(session.get(RauthyUserLinkRow,self.other).briareus_role,'user')
            from pydantic import ValidationError
            for action in ('user.link','user.role.set'):
                with self.assertRaises(ValidationError):
                    await command('admin',action,{})

    async def test_first_login_provisions_exact_subject_and_uses_private_provider_role(self):
        import json
        from sqlalchemy import select,func
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.ext.compiler import compiles
        from projects._control_ledger import OwnerAuditRow,OwnerOutboxRow
        from projects._rauthy_user_links import PlatformCurrentSubjectLinkReader
        from projects._rauthy_user_status import CurrentRauthyUserStatusReader,PrivateUserResponse,_PUBLIC_ISSUER
        @compiles(JSONB,'sqlite')
        def sqlite_json(type_,compiler,**kwargs):return 'JSON'
        for table in (OwnerAuditRow.__table__,OwnerOutboxRow.__table__):table.create(self.db.sql)
        subject='R'*24
        document={'id':subject,'email':'fixture@example.invalid','enabled':True,'roles':['admin'],'groups':['rauthy_admin']}
        response_status=200
        class Provider:
            async def read_user(self,**kwargs):
                self.subject=kwargs['subject']
                return PrivateUserResponse(response_status,'application/json',json.dumps(document).encode())
        provider=Provider()
        reader=PlatformCurrentSubjectLinkReader(database=self.db,rauthy_status=CurrentRauthyUserStatusReader(private_transport=provider))
        self.assertFalse(hasattr(provider,'subject')) # No background provider reads.
        first=await reader.current_link(issuer=_PUBLIC_ISSUER,subject=subject)
        self.assertEqual(first.role,'user') # Neither generic admin nor group grants superuser.
        self.assertEqual(provider.subject,subject)
        self.assertEqual((await reader.current_link(issuer=_PUBLIC_ISSUER,subject=subject)).user_id,first.user_id)
        with Session(self.db.sql) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(RauthyUserLinkRow)),1)
            self.assertEqual(session.scalar(select(func.count()).select_from(OwnerAuditRow)),1)
            self.assertEqual(session.scalar(select(func.count()).select_from(TeamMembershipRow)),0)
        document['roles']=['rauthy_admin']
        elevated=await reader.current_link(issuer=_PUBLIC_ISSUER,subject=subject)
        self.assertEqual(elevated.user_id,first.user_id)
        self.assertEqual(elevated.role,'operator')
        self.assertEqual(elevated.revision,2)
        document['roles']=[]
        self.assertEqual((await reader.current_link(issuer=_PUBLIC_ISSUER,subject=subject)).role,'user')
        document['roles']=['rauthy_admin']
        document['id']='S'*24
        fresh_admin=await reader.current_link(issuer=_PUBLIC_ISSUER,subject=document['id'])
        self.assertEqual(fresh_admin.role,'operator') # Administrator at first login, no manual action.
        self.assertNotEqual(fresh_admin.user_id,first.user_id) # Email does not merge accounts.
        document['enabled']=False
        self.assertIsNone(await reader.current_link(issuer=_PUBLIC_ISSUER,subject=document['id']))
        document['enabled']=True
        document['roles']=None
        with self.assertRaises(PlatformSubjectLinkUnavailable):
            await reader.current_link(issuer=_PUBLIC_ISSUER,subject=document['id'])
        response_status=404
        self.assertIsNone(await reader.current_link(issuer=_PUBLIC_ISSUER,subject='T'*24))
        with Session(self.db.sql) as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(RauthyUserLinkRow)),2)
