"""First-operator negative facts and both leases bound the single transaction."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from projects.application.bootstrap import BootstrapFirstOperator, BootstrapTransaction
from projects.domain.bootstrap import (
    FirstOperatorBootstrapDenied,
    FirstOperatorBootstrapUnavailable,
    VerifiedFirstOperatorApproval,
)
from projects.domain.user_links import VerifiedRauthyUserStatus
from projects.infrastructure.bootstrap import SqlBootstrapTransaction
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import TextClause

_ISSUER = "https://identity.example/auth/v1/"


class AuthorityFixture:
    def __init__(self, proof: VerifiedFirstOperatorApproval) -> None:
        self.proof = proof

    async def verify(self, evidence: object) -> VerifiedFirstOperatorApproval:
        if evidence != "signed-test-only":
            raise ValueError("Unsigned bootstrap attempt")
        return self.proof


class StatusFixture:
    def __init__(self, status: VerifiedRauthyUserStatus) -> None:
        self.status = status
        self.calls = 0

    async def current_status(self, *, issuer: str, subject: str) -> VerifiedRauthyUserStatus:
        if (issuer, subject) != (self.status.issuer, self.status.subject):
            raise AssertionError("Provider lookup scope changed")
        self.calls += 1
        return self.status


class OwnerTransactionFixture:
    def __init__(self, clock: list[datetime]) -> None:
        self.clock = clock
        self.retained_table: str | None = None
        self.queried: list[str] = []
        self.added: list[object] = []
        self.locked = False
        self.committed = False
        self.expire_on_flush = False
        self.expire_on_commit = False

    async def execute(self, _statement: TextClause, parameters: dict[str, int]) -> None:
        if parameters != {"namespace": 146536, "lock_id": 1}:
            raise AssertionError("Bootstrap must keep its exact owner-local lock")
        self.locked = True

    async def scalar(self, statement: Select[tuple[int]]) -> int | None:
        if not self.locked:
            raise AssertionError("The empty-owner fact must be protected by the shared lock")
        table = statement.get_final_froms()[0]
        name = str(table)
        self.queried.append(name)
        return 1 if name == self.retained_table else None

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        if self.expire_on_flush:
            self.clock[0] += timedelta(seconds=25)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[BootstrapTransaction]:
        try:
            yield SqlBootstrapTransaction(cast(AsyncSession, self))
        except Exception:
            self.added.clear()
            raise
        self.committed = True
        if self.expire_on_commit:
            self.clock[0] += timedelta(seconds=25)


class BootstrapUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 21, tzinfo=UTC)
        self.clock = [self.now]
        self.expiry = self.now + timedelta(seconds=20)
        proof = VerifiedFirstOperatorApproval(
            uuid4(),
            uuid4(),
            _ISSUER,
            "R" * 24,
            "briareus:platform:first-operator",
            True,
            True,
            uuid4(),
            "Workspace",
            self.expiry,
        )
        self.authority = AuthorityFixture(proof)
        self.status = StatusFixture(
            VerifiedRauthyUserStatus(_ISSUER, proof.rauthy_subject, True, self.expiry)
        )
        self.owner = OwnerTransactionFixture(self.clock)
        self.use_case = BootstrapFirstOperator(
            self.authority,
            self.status,
            self.owner,
            frozenset({_ISSUER}),
            lambda: self.clock[0],
        )

    async def test_bootstrap_checks_every_table_and_commits_all_six_records(self) -> None:
        current = await self.use_case.execute("signed-test-only")
        self.assertTrue(self.owner.committed)
        self.assertEqual(len(self.owner.added), 6)
        self.assertEqual(len(self.owner.queried), len(set(self.owner.queried)))
        self.assertIn("control.audit", self.owner.queried)
        self.assertIn("agents.identities", self.owner.queried)
        self.assertEqual(current.user_id, self.authority.proof.user_uuid)
        self.assertEqual(current.role, "operator")
        self.assertEqual(current.expires_at, self.expiry)

    async def test_retained_audit_denies_before_any_identity_or_project_write(self) -> None:
        self.owner.retained_table = "control.audit"
        with self.assertRaises(FirstOperatorBootstrapDenied):
            await self.use_case.execute("signed-test-only")
        self.assertFalse(self.owner.committed)
        self.assertEqual(self.owner.added, [])

    async def test_untrusted_provider_selector_is_rejected_before_provider_or_sql(self) -> None:
        for subject, issuer in (
            ("invalid/subject", _ISSUER),
            ("R" * 24, "https://foreign.invalid"),
        ):
            self.authority.proof = replace(
                self.authority.proof, rauthy_subject=subject, rauthy_issuer=issuer
            )
            with (
                self.subTest(subject=subject, issuer=issuer),
                self.assertRaises(FirstOperatorBootstrapDenied),
            ):
                await self.use_case.execute("signed-test-only")
        self.assertEqual(self.status.calls, 0)
        self.assertFalse(self.owner.locked)

    async def test_expiry_during_flush_aborts_the_whole_transaction(self) -> None:
        self.owner.expire_on_flush = True
        with self.assertRaises(FirstOperatorBootstrapDenied):
            await self.use_case.execute("signed-test-only")
        self.assertFalse(self.owner.committed)
        self.assertEqual(self.owner.added, [])

    async def test_expiry_during_commit_never_acknowledges_stale_operator_authority(self) -> None:
        self.owner.expire_on_commit = True
        with self.assertRaises(FirstOperatorBootstrapUnavailable):
            await self.use_case.execute("signed-test-only")
        self.assertTrue(self.owner.committed)
        self.assertEqual(len(self.owner.added), 6)

    async def test_expired_provider_status_cannot_enter_the_owner_transaction(self) -> None:
        self.status.status = replace(self.status.status, expires_at=self.now)
        with self.assertRaises(FirstOperatorBootstrapDenied):
            await self.use_case.execute("signed-test-only")
        self.assertFalse(self.owner.locked)
