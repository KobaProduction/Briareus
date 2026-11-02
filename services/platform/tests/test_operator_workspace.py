"""Operator visibility is an owner decision; ordinary membership stays bounded."""

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from postgres_fixture import PostgresOwnerFixture
from projects._oidc_membership_projection import (
    CurrentRauthyUserLink,
    PlatformOidcMembershipProjection,
    PlatformSubjectLinkUnavailable,
)
from projects._panel_management import ManagementError, ManagementQuery, PlatformAdministration
from projects._rauthy_user_links import RauthyUserLinkRow
from projects.domain.inventory import UserProfile

from projects._persistence import ProjectRow
from teams._persistence import TeamMembershipRow, TeamRow

_ISSUER, _SUBJECT = "https://identity.example", "fixture"


class UserLinkFixture:
    def __init__(self, actor):
        self.current = CurrentRauthyUserLink(
            _ISSUER, _SUBJECT, actor, True, "user", 1, datetime.now(UTC) + timedelta(seconds=25)
        )

    async def current_link(self, **kwargs):
        return self.current


class OperatorWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.actor, self.other, self.team, self.project, self.personal = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        self.db = PostgresOwnerFixture()
        await self.db.initialize()
        self.links = UserLinkFixture(self.actor)
        self.source = PlatformOidcMembershipProjection(database=self.db, subject_links=self.links)
        async with self.db.transaction() as session:
            session.add(TeamRow(id=self.team, name="Other team", owner_user_id=self.other))
            session.add(ProjectRow(id=self.project, name="Team project", owner_team_id=self.team))
            session.add(
                ProjectRow(id=self.personal, name="Other personal", owner_user_id=self.other)
            )

    async def asyncTearDown(self):
        await self.db.close()

    async def test_large_operator_directory_keeps_identity_and_pages_all_projects(self):
        self.links.current = replace(self.links.current, role="operator")
        async with self.db.transaction() as session:
            for index in range(105):
                session.add(
                    ProjectRow(id=uuid4(), name="Project " + str(index), owner_user_id=self.actor)
                )
        current = await self.source.resolve(issuer=_ISSUER, subject=_SUBJECT)
        self.assertTrue(current.directory_paged)
        self.assertEqual(current.projects, ())
        self.assertIsNotNone(
            await self.source.resolve_project(
                issuer=_ISSUER, subject=_SUBJECT, project_uuid=self.project
            )
        )
        from projects._panel_directory import read_directory

        service = SimpleNamespace(db=self.db, projection=self.source)
        cursor = None
        found = set()
        while True:
            reply = await read_directory(
                service,
                ManagementQuery(
                    issuer=_ISSUER,
                    subject=_SUBJECT,
                    operation_uuid=uuid4(),
                    action="directory",
                    data={"kind": "projects", "limit": 25, "cursor": cursor},
                ),
                current,
                datetime.now(UTC) + timedelta(seconds=20),
            )
            found.update(row.id for row in reply.items)
            if not reply.has_more:
                break
            self.assertIsNotNone(reply.next_cursor)
            cursor = reply.next_cursor
        self.assertEqual(len(found), 107)

    async def test_agent_directory_is_project_scoped_and_paged(self):
        from projects._panel_agents import read_agents

        from agents._persistence import AgentIdentityRow

        own = uuid4()
        first = uuid4()
        second = uuid4()
        foreign = uuid4()
        async with self.db.transaction() as session:
            session.add(ProjectRow(id=own, name="Owned", owner_user_id=self.actor))
            session.add_all(
                [
                    AgentIdentityRow(id=first, project_id=own, name="First"),
                    AgentIdentityRow(id=second, project_id=own, name="Second"),
                    AgentIdentityRow(id=foreign, project_id=self.personal, name="Foreign"),
                ]
            )
        actor = await self.source.resolve(issuer=_ISSUER, subject=_SUBJECT)
        service = SimpleNamespace(db=self.db, projection=self.source)

        async def call(action, data):
            return await read_agents(
                service,
                ManagementQuery(
                    issuer=_ISSUER,
                    subject=_SUBJECT,
                    operation_uuid=uuid4(),
                    action=action,
                    data=data,
                ),
                actor,
                datetime.now(UTC) + timedelta(seconds=20),
            )

        page = await call("agents.list", {"project_uuid": str(own), "limit": 1})
        self.assertTrue(page.has_more)
        next_page = await call(
            "agents.list", {"project_uuid": str(own), "limit": 1, "cursor": page.next_cursor}
        )
        self.assertEqual(
            {row.id for row in page.items + next_page.items}, {str(first), str(second)}
        )
        with self.assertRaises(ManagementError) as caught:
            await call("agents.get", {"project_uuid": str(own), "id": str(foreign)})
        self.assertEqual(caught.exception.status, 404)
        with self.assertRaises(ManagementError) as caught:
            await call("agents.list", {"project_uuid": str(self.personal)})
        self.assertEqual(caught.exception.status, 403)

    async def test_regular_user_cannot_list_or_resolve_foreign_projects(self):
        result = await self.source.resolve(issuer=_ISSUER, subject=_SUBJECT)
        self.assertEqual(result.teams, ())
        self.assertEqual(result.projects, ())
        for project in (self.project, self.personal):
            self.assertIsNone(
                await self.source.resolve_project(
                    issuer=_ISSUER, subject=_SUBJECT, project_uuid=project
                )
            )

    async def test_operator_sees_real_owners_without_becoming_a_member(self):
        self.links.current = replace(self.links.current, role="operator")
        result = await self.source.resolve(issuer=_ISSUER, subject=_SUBJECT)
        self.assertEqual({p.project_id for p in result.projects}, {self.project, self.personal})
        self.assertFalse(result.teams[0].member)
        self.assertFalse(result.teams[0].owner)
        personal = next(p for p in result.projects if p.project_id == self.personal)
        self.assertEqual(personal.owner_id, self.other)
        for project in (self.project, self.personal):
            exact = await self.source.resolve_project(
                issuer=_ISSUER, subject=_SUBJECT, project_uuid=project
            )
            self.assertEqual(len(exact.projects), 1)
            self.assertIn("use_resources", exact.projects[0].permissions)
        self.links.current = replace(self.links.current, role="user")
        self.assertIsNone(
            await self.source.resolve_project(
                issuer=_ISSUER, subject=_SUBJECT, project_uuid=self.project
            )
        )

    async def test_member_directory_is_team_scoped_and_never_unlocks_global_administration(self):
        async def profile(issuer, subject):
            return UserProfile(subject, subject + "@example.invalid", True)

        service = SimpleNamespace(db=self.db, projection=self.source, profile=profile)
        deadline = datetime.now(UTC) + timedelta(seconds=20)
        query = ManagementQuery(
            issuer=_ISSUER,
            subject=_SUBJECT,
            operation_uuid=uuid4(),
            action="team.read",
            data={"id": str(self.team)},
        )
        with self.assertRaises(ManagementError):
            await PlatformAdministration.execute(service, query, deadline)
        async with self.db.transaction() as session:
            session.add(TeamMembershipRow(team_id=self.team, user_id=self.actor, active=True))
            for actor, subject in ((self.actor, "member"), (uuid4(), "unrelated")):
                session.add(
                    RauthyUserLinkRow(
                        user_id=actor,
                        issuer=_ISSUER,
                        subject=subject,
                        briareus_role="user",
                        active=True,
                        version=1,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
        result = await PlatformAdministration.execute(service, query, deadline)
        self.assertEqual([person.id for person in result.users], [str(self.actor)])
        self.assertEqual([project.id for project in result.projects], [str(self.project)])
        self.assertEqual([team.id for team in result.teams], [str(self.team)])
        with self.assertRaises(ManagementError):
            await PlatformAdministration.execute(
                service, query.model_copy(update={"action": "inventory", "data": {}}), deadline
            )

    async def test_only_operator_grants_inviter_and_team_ownership_does_not_imply_it(self):
        from unittest.mock import patch

        now = datetime.now(UTC)
        for user_id, subject, role in (
            (self.actor, "admin", "operator"),
            (self.other, "member", "user"),
        ):
            async with self.db.transaction() as session:
                session.add(
                    RauthyUserLinkRow(
                        user_id=user_id,
                        issuer=_ISSUER,
                        subject=subject,
                        briareus_role=role,
                        active=True,
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )

        async def resolve(**query):
            admin = query["subject"] == "admin"
            return SimpleNamespace(
                user_id=self.actor if admin else self.other,
                role="operator" if admin else "user",
                expires_at=now + timedelta(seconds=25),
                teams=(SimpleNamespace(owner=True),),
            )

        service = SimpleNamespace(
            db=self.db, projection=SimpleNamespace(resolve=resolve), provider=SimpleNamespace()
        )

        async def command(subject, action, data, operation=None):
            query = ManagementQuery(
                issuer=_ISSUER,
                subject=subject,
                operation_uuid=operation or uuid4(),
                action=action,
                data=data,
            )
            return await PlatformAdministration.execute(service, query, now + timedelta(seconds=20))

        with patch.dict("os.environ", {"RAUTHY_INVITATION_EMAIL_READY": "0"}):
            self.assertFalse((await command("member", "invitation.capabilities", {})).can_invite)
            for action, data in [
                ("invitation.issue", {"email": "fixture@example.invalid"}),
                ("inviter.set", {"user_id": str(self.other), "enabled": True}),
            ]:
                with self.assertRaises(ManagementError) as denied:
                    await command("member", action, data)
                self.assertEqual(denied.exception.status, 403)
            operation = uuid4()
            result = await command(
                "admin", "inviter.set", {"user_id": str(self.other), "enabled": True}, operation
            )
            self.assertEqual(
                await command(
                    "admin", "inviter.set", {"user_id": str(self.other), "enabled": True}, operation
                ),
                result,
            )
            self.assertTrue((await command("member", "invitation.capabilities", {})).can_invite)
            with self.assertRaises(ManagementError) as mail:
                await command("member", "invitation.issue", {"email": "fixture@example.invalid"})
            self.assertEqual(mail.exception.code, "RAUTHY_INVITATION_MAIL_UNCONFIGURED")
            await command("admin", "inviter.set", {"user_id": str(self.other), "enabled": False})
            self.assertFalse((await command("member", "invitation.capabilities", {})).can_invite)
            async with self.db.transaction() as session:
                self.assertEqual(
                    (await session.get(RauthyUserLinkRow, self.other)).briareus_role, "user"
                )
            from pydantic import ValidationError

            for action in ("user.link", "user.role.set"):
                with self.assertRaises(ValidationError):
                    await command("admin", action, {})

    async def test_first_login_provisions_exact_subject_and_uses_private_provider_role(self):
        import json

        from projects._rauthy_user_links import PlatformCurrentSubjectLinkReader
        from projects._rauthy_user_status import (
            _PUBLIC_ISSUER,
            CurrentRauthyUserStatusReader,
            PrivateUserResponse,
        )
        from sqlalchemy import func, select

        from projects._control_ledger import OwnerAuditRow

        subject = "R" * 24
        document = {
            "id": subject,
            "email": "fixture@example.invalid",
            "enabled": True,
            "roles": ["admin"],
            "groups": ["rauthy_admin"],
        }
        response_status = 200

        class Provider:
            async def read_user(self, **kwargs):
                self.subject = kwargs["subject"]
                return PrivateUserResponse(
                    response_status, "application/json", json.dumps(document).encode()
                )

        provider = Provider()
        reader = PlatformCurrentSubjectLinkReader(
            database=self.db,
            rauthy_status=CurrentRauthyUserStatusReader(private_transport=provider),
        )
        self.assertFalse(hasattr(provider, "subject"))  # No background provider reads.
        first = await reader.current_link(issuer=_PUBLIC_ISSUER, subject=subject)
        self.assertEqual(first.role, "user")  # Neither generic admin nor group grants superuser.
        self.assertEqual(provider.subject, subject)
        self.assertEqual(
            (await reader.current_link(issuer=_PUBLIC_ISSUER, subject=subject)).user_id,
            first.user_id,
        )
        async with self.db.transaction() as session:
            self.assertEqual(
                await session.scalar(select(func.count()).select_from(RauthyUserLinkRow)), 1
            )
            self.assertEqual(
                await session.scalar(select(func.count()).select_from(OwnerAuditRow)), 1
            )
            self.assertEqual(
                await session.scalar(select(func.count()).select_from(TeamMembershipRow)), 0
            )
        document["roles"] = ["rauthy_admin"]
        elevated = await reader.current_link(issuer=_PUBLIC_ISSUER, subject=subject)
        self.assertEqual(elevated.user_id, first.user_id)
        self.assertEqual(elevated.role, "operator")
        self.assertEqual(elevated.revision, 2)
        document["roles"] = []
        self.assertEqual(
            (await reader.current_link(issuer=_PUBLIC_ISSUER, subject=subject)).role, "user"
        )
        document["roles"] = ["rauthy_admin"]
        document["id"] = "S" * 24
        fresh_admin = await reader.current_link(issuer=_PUBLIC_ISSUER, subject=document["id"])
        self.assertEqual(
            fresh_admin.role, "operator"
        )  # Administrator at first login, no manual action.
        self.assertNotEqual(fresh_admin.user_id, first.user_id)  # Email does not merge accounts.
        document["enabled"] = False
        self.assertIsNone(await reader.current_link(issuer=_PUBLIC_ISSUER, subject=document["id"]))
        document["enabled"] = True
        document["roles"] = None
        with self.assertRaises(PlatformSubjectLinkUnavailable):
            await reader.current_link(issuer=_PUBLIC_ISSUER, subject=document["id"])
        response_status = 404
        self.assertIsNone(await reader.current_link(issuer=_PUBLIC_ISSUER, subject="T" * 24))
        async with self.db.transaction() as session:
            self.assertEqual(
                await session.scalar(select(func.count()).select_from(RauthyUserLinkRow)), 2
            )
