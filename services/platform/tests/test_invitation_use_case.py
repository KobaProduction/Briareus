"""Invitation intent and current authority bound the non-idempotent provider call."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from projects.application.invitations import (
    InvitationActor,
    InvitationCommand,
    InvitationIdentity,
    InvitationTransaction,
    IssueInvitation,
    ManageInvitations,
    SetInviter,
)
from projects.domain.invitations import (
    InvitationCapabilities,
    InvitationEmail,
    InvitationOutcome,
    InvitationResult,
    InviterOutcome,
    ProviderUser,
)
from projects.domain.management import ManagementError


class InvitationLedgerFixture:
    def __init__(self) -> None:
        self.state: str | None = None
        self.result: InvitationResult | None = None
        self.allowed = True
        self.in_transaction = False
        self.intent_committed = False
        self.events: list[str] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[InvitationTransaction]:
        self.in_transaction = True
        try:
            yield self
        finally:
            self.in_transaction = False
        if self.state == "issuing":
            self.intent_committed = True

    async def capabilities(
        self,
        _identity: InvitationIdentity,
        _actor: InvitationActor,
    ) -> InvitationCapabilities:
        return InvitationCapabilities(self.allowed, False, (), None)

    async def lock(self, _command: InvitationCommand) -> None:
        pass

    async def require_actor(self, _command: InvitationCommand) -> None:
        if not self.allowed:
            raise ManagementError(403, "INVITER_REQUIRED")

    async def previous(self, _command: InvitationCommand) -> InvitationResult | None:
        if self.state == "issuing":
            raise ManagementError(409, "INVITATION_OUTCOME_UNCONFIRMED")
        return self.result

    async def set_inviter(
        self,
        _command: InvitationCommand,
        change: SetInviter,
    ) -> InviterOutcome:
        return InviterOutcome(str(change.user_uuid), change.enabled)

    async def record_intent(
        self,
        _command: InvitationCommand,
        _change: IssueInvitation,
    ) -> None:
        self.state = "issuing"
        self.events.append("intent")

    async def finish(self, _command: InvitationCommand, user: ProviderUser) -> InvitationOutcome:
        result = InvitationOutcome(user.subject)
        self.state, self.result = "provider_created", result
        self.events.append("finish")
        return result


class ProviderFixture:
    def __init__(self, ledger: InvitationLedgerFixture) -> None:
        self.ledger = ledger
        self.creations = 0
        self.status = 404
        self.lose_response = False
        self.revoke = False

    def unavailable_reason(self) -> str | None:
        return None

    async def lookup(self, _email: InvitationEmail) -> int:
        if self.ledger.in_transaction:
            raise AssertionError("Provider lookup must not run inside the owner transaction")
        return self.status

    async def create(self, _email: InvitationEmail) -> ProviderUser:
        if self.ledger.in_transaction or not self.ledger.intent_committed:
            raise AssertionError("Durable intent must commit before contacting the provider")
        self.creations += 1
        self.ledger.events.append("provider")
        if self.lose_response:
            raise TimeoutError
        if self.revoke:
            self.ledger.allowed = False
        return ProviderUser("R" * 24)


class AuthorityFixture:
    def __init__(self, expiry: datetime) -> None:
        self.expiry: datetime | None = expiry

    async def fresh_expiry(
        self,
        _identity: InvitationIdentity,
        _actor: InvitationActor,
    ) -> datetime | None:
        return self.expiry


class InvitationUseCaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 21, tzinfo=UTC)
        self.deadline = self.now + timedelta(seconds=20)
        self.ledger = InvitationLedgerFixture()
        self.provider = ProviderFixture(self.ledger)
        self.authority = AuthorityFixture(self.deadline)
        self.command = InvitationCommand(
            InvitationIdentity("https://identity.example", "actor"),
            InvitationActor(uuid4(), False),
            uuid4(),
            "digest",
            IssueInvitation(InvitationEmail.parse("Person@example.invalid")),
        )
        self.use_case = ManageInvitations(
            self.ledger,
            self.provider,
            self.authority,
            lambda: self.now,
        )

    async def test_intent_precedes_provider_and_confirmed_replay_never_resends(self) -> None:
        result = await self.use_case.execute(self.command, self.deadline)
        self.assertEqual(self.ledger.events, ["intent", "provider", "finish"])
        self.assertEqual(result, InvitationOutcome("R" * 24))
        self.assertEqual(await self.use_case.execute(self.command, self.deadline), result)
        self.assertEqual(self.provider.creations, 1)

    async def test_lost_provider_result_is_durable_and_never_retried(self) -> None:
        self.provider.lose_response = True
        for status in (503, 409):
            with self.assertRaises(ManagementError) as raised:
                await self.use_case.execute(self.command, self.deadline)
            self.assertEqual(raised.exception.status, status)
            self.assertEqual(raised.exception.code, "INVITATION_OUTCOME_UNCONFIRMED")
        self.assertEqual(self.ledger.state, "issuing")
        self.assertEqual(self.provider.creations, 1)

    async def test_existing_account_never_receives_an_intent_or_membership(self) -> None:
        self.provider.status = 200
        with self.assertRaises(ManagementError) as raised:
            await self.use_case.execute(self.command, self.deadline)
        self.assertEqual(raised.exception.code, "RAUTHY_ACCOUNT_ALREADY_EXISTS")
        self.assertIsNone(self.ledger.state)
        self.assertEqual(self.provider.creations, 0)

    async def test_authority_removed_after_provider_call_leaves_outcome_unconfirmed(self) -> None:
        self.authority.expiry = None
        with self.assertRaises(ManagementError) as raised:
            await self.use_case.execute(self.command, self.deadline)
        self.assertEqual(raised.exception.code, "INVITATION_OUTCOME_UNCONFIRMED")
        self.assertEqual(self.ledger.state, "issuing")
        self.assertNotIn("finish", self.ledger.events)

    async def test_inviter_revocation_before_finalize_is_not_reported_as_success(self) -> None:
        self.provider.revoke = True
        with self.assertRaises(ManagementError) as raised:
            await self.use_case.execute(self.command, self.deadline)
        self.assertEqual(raised.exception.status, 503)
        self.assertEqual(raised.exception.code, "INVITATION_OUTCOME_UNCONFIRMED")
        self.assertEqual(self.ledger.state, "issuing")

    async def test_expired_request_never_records_intent(self) -> None:
        with self.assertRaises(ManagementError):
            await self.use_case.execute(self.command, self.now)
        self.assertIsNone(self.ledger.state)
        self.assertEqual(self.provider.creations, 0)
