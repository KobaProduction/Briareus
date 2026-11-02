"""Reauthorize before both execution and replay inside one durable transaction."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel

from authorization.domain.idempotency import ReplayRecord

ReceiptT = TypeVar("ReceiptT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class CommandOutcome[ReceiptT: BaseModel]:
    status: int
    body: ReceiptT


class ConcurrentReplayClaim(Exception):
    """A unique claim conflicted after waiting for another transaction."""


class ReplayTransactionPort[ReceiptT: BaseModel](Protocol):
    async def reauthorize(self) -> None: ...
    async def find(self) -> ReplayRecord | None: ...
    def replay(self, record: ReplayRecord, fingerprint: str) -> CommandOutcome[ReceiptT]: ...
    async def claim(self, fingerprint: str) -> UUID: ...
    async def perform(self) -> CommandOutcome[ReceiptT]: ...
    def complete(self, claim_uuid: UUID, outcome: CommandOutcome[ReceiptT]) -> None: ...


class ReplayTransactionFactoryPort[ReceiptT: BaseModel](Protocol):
    def open(self) -> AbstractAsyncContextManager[ReplayTransactionPort[ReceiptT]]: ...


class ExecuteIdempotentCommand[ReceiptT: BaseModel]:
    def __init__(self, transactions: ReplayTransactionFactoryPort[ReceiptT]) -> None:
        self.transactions = transactions

    async def execute(self, fingerprint: str) -> CommandOutcome[ReceiptT]:
        try:
            async with self.transactions.open() as transaction:
                # A removed member must not retrieve an old secret/result by key.
                await transaction.reauthorize()
                previous = await transaction.find()
                if previous is not None:
                    return transaction.replay(previous, fingerprint)
                claim_uuid = await transaction.claim(fingerprint)
                outcome = await transaction.perform()
                transaction.complete(claim_uuid, outcome)
                return outcome
        except ConcurrentReplayClaim:
            # The DB unique constraint waited for the winning commit/rollback.
            async with self.transactions.open() as transaction:
                await transaction.reauthorize()
                previous = await transaction.find()
                if previous is None:
                    raise
                return transaction.replay(previous, fingerprint)
