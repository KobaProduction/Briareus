"""Authority expiry and visibility are preserved across a paged directory read."""

import unittest
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from projects.application.directory import DirectoryError, DirectoryQuery, ReadDirectory
from projects.domain.directory import DirectoryActor, DirectoryItem, DirectoryTeam


@dataclass
class ReadFixture:
    rows: tuple[DirectoryItem, ...]
    read_completed: bool = False

    async def read(
        self, _query: DirectoryQuery, _actor: DirectoryActor
    ) -> tuple[DirectoryItem, ...]:
        self.read_completed = True
        return self.rows


@dataclass
class AuthorityFixture:
    reader: ReadFixture
    actor: DirectoryActor | None

    async def current(self, _issuer: str, _subject: str) -> DirectoryActor | None:
        if not self.reader.read_completed:
            raise AssertionError("Authority must be revalidated after the owner read")
        return self.actor


class DirectoryUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def test_query_bounds_are_enforced_without_the_panel_adapter(self) -> None:
        for limit in (0, -1, 101, True):
            with self.subTest(limit=limit), self.assertRaises(DirectoryError) as raised:
                DirectoryQuery("https://identity.example", "actor", "teams", limit, None)
            self.assertEqual(raised.exception.code, "DIRECTORY_QUERY_INVALID")

    def setUp(self) -> None:
        self.now = datetime(2026, 10, 21, tzinfo=UTC)
        self.actor = DirectoryActor(uuid4(), "operator", self.now + timedelta(seconds=20))
        self.query = DirectoryQuery("https://identity.example", "actor", "teams", 1, None)
        self.first = DirectoryTeam(str(uuid4()), "First", False, False)
        self.second = DirectoryTeam(str(uuid4()), "Second", False, False)
        self.reader = ReadFixture((self.first, self.second))
        self.authority = AuthorityFixture(self.reader, self.actor)
        self.use_case = ReadDirectory(self.reader, self.authority, lambda: self.now)

    async def test_page_uses_last_visible_id_without_granting_membership(self) -> None:
        page = await self.use_case.execute(self.query, self.actor, self.actor.expires_at)
        self.assertEqual(page.items, (self.first,))
        self.assertTrue(page.has_more)
        self.assertEqual(page.next_cursor, self.first.id)
        self.assertFalse(self.first.member)
        self.assertFalse(self.first.owner)

    async def test_empty_page_has_no_cursor(self) -> None:
        self.reader.rows = ()
        page = await self.use_case.execute(self.query, self.actor, self.actor.expires_at)
        self.assertEqual(page.items, ())
        self.assertFalse(page.has_more)
        self.assertIsNone(page.next_cursor)

    async def test_authority_removed_or_replaced_during_read_is_denied(self) -> None:
        for fresh in (None, replace(self.actor, user_id=uuid4()), replace(self.actor, role="user")):
            with self.subTest(fresh=fresh):
                self.authority.actor = fresh
                with self.assertRaises(DirectoryError) as raised:
                    await self.use_case.execute(self.query, self.actor, self.actor.expires_at)
                self.assertEqual(raised.exception.code, "DIRECTORY_AUTHORITY_CHANGED")

    async def test_original_deadline_and_fresh_expiry_both_bound_the_read(self) -> None:
        for deadline, fresh_expiry in (
            (self.now, self.actor.expires_at),
            (self.actor.expires_at, self.now),
        ):
            with self.subTest(deadline=deadline, fresh_expiry=fresh_expiry):
                self.authority.actor = replace(self.actor, expires_at=fresh_expiry)
                with self.assertRaises(DirectoryError):
                    await self.use_case.execute(self.query, self.actor, deadline)

    def test_approval_policy_uses_actual_ownership_or_operator_role(self) -> None:
        ordinary = replace(self.actor, role="user")
        self.assertFalse(ordinary.can_approve(uuid4(), uuid4()))
        self.assertTrue(ordinary.can_approve(ordinary.user_id, None))
        self.assertTrue(ordinary.can_approve(None, ordinary.user_id))
        self.assertTrue(self.actor.can_approve(uuid4(), uuid4()))
