"""Exact ownership and time-bound provider evidence govern current membership."""

import unittest
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from projects.application.membership import ResolveMembership
from projects.domain.membership import (
    CurrentRauthyUserLink,
    MembershipFacts,
    PlatformSubjectLinkUnavailable,
    PlatformTeamMembership,
    ProjectOwnership,
)


@dataclass
class SubjectFixture:
    current: CurrentRauthyUserLink | None

    async def current_link(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None:
        if self.current is not None and (issuer, subject) != (
            self.current.issuer,
            self.current.subject,
        ):
            return None
        return self.current


@dataclass
class OwnershipFixture:
    facts: MembershipFacts
    clock: list[datetime]
    advance: timedelta = timedelta(0)
    requested: UUID | None = None

    async def directory(self, _actor: CurrentRauthyUserLink) -> MembershipFacts:
        self.clock[0] += self.advance
        return self.facts

    async def project(
        self, _actor: CurrentRauthyUserLink, project_uuid: UUID
    ) -> MembershipFacts | None:
        self.requested = project_uuid
        self.clock[0] += self.advance
        return self.facts


class MembershipUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 21, tzinfo=UTC)
        self.clock = [self.now]
        self.actor = CurrentRauthyUserLink(
            "https://identity.example",
            "actor",
            uuid4(),
            True,
            "user",
            1,
            self.now + timedelta(seconds=20),
        )
        self.project = ProjectOwnership(uuid4(), "Project", self.actor.user_id, None)
        self.subject = SubjectFixture(self.actor)
        self.reader = OwnershipFixture(MembershipFacts((), (self.project,)), self.clock)
        self.use_case = ResolveMembership(self.subject, self.reader, lambda: self.clock[0])

    async def test_exact_selector_is_independent_of_paged_directory(self) -> None:
        self.reader.facts = MembershipFacts((), (), True)
        paged = await self.use_case.directory(issuer=self.actor.issuer, subject=self.actor.subject)
        self.assertIsNotNone(paged)
        assert paged is not None
        self.assertTrue(paged.directory_paged)
        self.reader.facts = MembershipFacts((), (self.project,))
        exact = await self.use_case.project(
            issuer=self.actor.issuer,
            subject=self.actor.subject,
            project_uuid=self.project.uuid,
        )
        self.assertIsNotNone(exact)
        assert exact is not None
        self.assertEqual(self.reader.requested, self.project.uuid)
        self.assertEqual(exact.projects[0].owner_id, self.actor.user_id)

    async def test_disabled_provider_link_does_not_read_owner_facts(self) -> None:
        self.subject.current = replace(self.actor, enabled=False)
        self.assertIsNone(
            await self.use_case.project(
                issuer=self.actor.issuer,
                subject=self.actor.subject,
                project_uuid=self.project.uuid,
            )
        )
        self.assertIsNone(self.reader.requested)

    async def test_provider_lease_expiring_during_sql_cannot_return_membership(self) -> None:
        self.reader.advance = timedelta(seconds=21)
        with self.assertRaises(PlatformSubjectLinkUnavailable):
            await self.use_case.project(
                issuer=self.actor.issuer,
                subject=self.actor.subject,
                project_uuid=self.project.uuid,
            )

    def test_team_membership_grants_use_but_approval_requires_real_owner(self) -> None:
        team_uuid = uuid4()
        project = ProjectOwnership(uuid4(), "Team project", None, team_uuid)
        member = PlatformTeamMembership(team_uuid, False, "Team", True)
        self.assertEqual(project.membership(self.actor, (member,)).permissions, ("use_resources",))
        owner = replace(member, owner=True)
        self.assertEqual(
            project.membership(self.actor, (owner,)).permissions,
            ("use_resources", "approve_agent_session"),
        )
        with self.assertRaises(PlatformSubjectLinkUnavailable):
            project.membership(self.actor, (replace(member, member=False),))

    def test_operator_visibility_does_not_change_the_real_personal_owner(self) -> None:
        project = replace(self.project, owner_user_uuid=uuid4())
        with self.assertRaises(PlatformSubjectLinkUnavailable):
            project.membership(self.actor, ())
        result = project.membership(replace(self.actor, role="operator"), ())
        self.assertEqual(result.owner_id, project.owner_user_uuid)
        self.assertNotEqual(result.owner_id, self.actor.user_id)
