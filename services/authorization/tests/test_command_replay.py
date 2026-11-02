"""Transaction order and reauthorization are required even for persisted replay."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest import IsolatedAsyncioTestCase
from uuid import UUID, uuid4

from pydantic import BaseModel

from authorization.application.idempotency import (
    CommandOutcome,
    ConcurrentReplayClaim,
    ExecuteIdempotentCommand,
    ReplayTransactionPort,
)
from authorization.domain.idempotency import ReplayFingerprintConflict, ReplayPending, ReplayRecord


class ReplayReceipt(BaseModel):
    value: str


class ReplayTransaction:
    def __init__(self, *, previous: ReplayRecord | None = None, collide: bool = False) -> None:
        self.previous = previous
        self.collide = collide
        self.calls: list[str] = []
        self.claim_uuid = uuid4()

    async def reauthorize(self) -> None:
        self.calls.append("authorize")

    async def find(self) -> ReplayRecord | None:
        self.calls.append("find")
        return self.previous

    def replay(self, record: ReplayRecord, fingerprint: str) -> CommandOutcome[ReplayReceipt]:
        record.require_completed(fingerprint)
        self.calls.append("replay")
        return CommandOutcome(200, ReplayReceipt(value="stored"))

    async def claim(self, fingerprint: str) -> UUID:
        _ = fingerprint
        self.calls.append("claim")
        if self.collide:
            raise ConcurrentReplayClaim
        return self.claim_uuid

    async def perform(self) -> CommandOutcome[ReplayReceipt]:
        self.calls.append("perform")
        return CommandOutcome(201, ReplayReceipt(value="new"))

    def complete(self, claim_uuid: UUID, outcome: CommandOutcome[ReplayReceipt]) -> None:
        assert claim_uuid == self.claim_uuid and outcome.status == 201
        self.calls.append("complete")


class ReplayTransactions:
    def __init__(self, *transactions: ReplayTransaction) -> None:
        self.transactions = list(transactions)

    @asynccontextmanager
    async def open(self) -> AsyncIterator[ReplayTransactionPort[ReplayReceipt]]:
        yield self.transactions.pop(0)


class CommandReplayTests(IsolatedAsyncioTestCase):
    async def test_new_claim_performs_and_completes_after_authorization(self) -> None:
        transaction = ReplayTransaction()
        result = await ExecuteIdempotentCommand(ReplayTransactions(transaction)).execute(
            "fingerprint"
        )
        self.assertEqual(transaction.calls, ["authorize", "find", "claim", "perform", "complete"])
        self.assertEqual(result.body.value, "new")

    async def test_stored_result_is_reauthorized_without_repeating_effect(self) -> None:
        transaction = ReplayTransaction(
            previous=ReplayRecord("fingerprint", "completed", 200, "ciphertext")
        )
        result = await ExecuteIdempotentCommand(ReplayTransactions(transaction)).execute(
            "fingerprint"
        )
        self.assertEqual(transaction.calls, ["authorize", "find", "replay"])
        self.assertEqual(result.body.value, "stored")

    async def test_unique_collision_reauthorizes_in_new_transaction(self) -> None:
        first = ReplayTransaction(collide=True)
        second = ReplayTransaction(
            previous=ReplayRecord("fingerprint", "completed", 200, "ciphertext")
        )
        result = await ExecuteIdempotentCommand(ReplayTransactions(first, second)).execute(
            "fingerprint"
        )
        self.assertEqual(first.calls, ["authorize", "find", "claim"])
        self.assertEqual(second.calls, ["authorize", "find", "replay"])
        self.assertEqual(result.body.value, "stored")

    async def test_changed_payload_or_pending_claim_never_executes_again(self) -> None:
        for record, error in (
            (ReplayRecord("different", "completed", 200, "ciphertext"), ReplayFingerprintConflict),
            (ReplayRecord("fingerprint", "pending", None, None), ReplayPending),
        ):
            transaction = ReplayTransaction(previous=record)
            with self.assertRaises(error):
                await ExecuteIdempotentCommand(ReplayTransactions(transaction)).execute(
                    "fingerprint"
                )
            self.assertEqual(transaction.calls, ["authorize", "find"])
