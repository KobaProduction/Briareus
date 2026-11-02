"""Framework-free lifetime/race regression tests for bounded read authority."""

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from authorization.application.files_read import DecideFilesRead
from authorization.domain.files_read import (
    ReadAuthenticationRequired,
    ReadCaller,
    ReadGrant,
    ReadResource,
    ReadScope,
    ReadScopeDenied,
)


class AuthorityFixture:
    def __init__(self, grant: ReadGrant, resource: ReadResource) -> None:
        self.grant = grant
        self.initial = resource
        self.current = resource
        self.calls: list[str] = []

    def current_resource(self) -> ReadResource:
        self.calls.append("resource")
        return self.initial if len(self.calls) == 1 else self.current

    async def current_grant(self) -> ReadGrant:
        self.calls.append("grant")
        return self.grant


class ClockFixture:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class FilesReadUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 21, tzinfo=UTC)
        actor, project, session = uuid4(), uuid4(), uuid4()
        self.scope = ReadScope(project, session, "bound-effect", 4, 7)
        self.caller = ReadCaller(
            actor,
            project,
            session,
            "hand",
            "rauthy",
            "briareus:access",
            "bound-effect",
            self.now + timedelta(seconds=15),
        )
        grant = ReadGrant(actor, project, session, 4, self.now + timedelta(seconds=10))
        self.sources = AuthorityFixture(grant, ReadResource(7, self.now + timedelta(seconds=12)))
        self.use_case = DecideFilesRead(self.sources, ClockFixture(self.now))

    async def test_revalidates_resource_after_grant_and_caps_lifetime(self) -> None:
        result = await self.use_case.execute(self.scope, self.caller)
        self.assertEqual(self.sources.calls, ["resource", "grant", "resource"])
        self.assertEqual(result.expires_at, self.now + timedelta(seconds=5))

    async def test_new_resource_proof_cannot_extend_initial_lifetime(self) -> None:
        self.sources.initial = ReadResource(7, self.now + timedelta(seconds=1))
        result = await self.use_case.execute(self.scope, self.caller)
        self.assertEqual(result.expires_at, self.sources.initial.expires_at)

    async def test_resource_revision_change_during_grant_read_denied(self) -> None:
        self.sources.current = replace(self.sources.current, revision=8)
        with self.assertRaises(ReadScopeDenied):
            await self.use_case.execute(self.scope, self.caller)

    async def test_expired_original_resource_denied_despite_fresh_replacement(self) -> None:
        self.sources.initial = ReadResource(7, self.now)
        with self.assertRaises(ReadScopeDenied):
            await self.use_case.execute(self.scope, self.caller)

    async def test_stale_grant_revision_denied(self) -> None:
        self.sources.grant = replace(self.sources.grant, revision=3)
        with self.assertRaises(ReadScopeDenied):
            await self.use_case.execute(self.scope, self.caller)

    async def test_grant_cannot_outlive_caller(self) -> None:
        caller = replace(self.caller, expires_at=self.now + timedelta(seconds=8))
        with self.assertRaises(ReadScopeDenied):
            await self.use_case.execute(self.scope, caller)

    async def test_wrong_effect_fails_before_accessing_authority(self) -> None:
        caller = replace(self.caller, effect_key="another-effect")
        with self.assertRaises(ReadAuthenticationRequired):
            await self.use_case.execute(self.scope, caller)
        self.assertEqual(self.sources.calls, [])

    async def test_expired_caller_fails_before_accessing_authority(self) -> None:
        caller = replace(self.caller, expires_at=self.now)
        with self.assertRaises(ReadAuthenticationRequired):
            await self.use_case.execute(self.scope, caller)
        self.assertEqual(self.sources.calls, [])
