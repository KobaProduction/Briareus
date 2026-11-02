"""Access ledger adapter; one transaction covers claim, effect and ciphertext."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_persistence import IdempotencyRow
from authorization.application.idempotency import (
    CommandOutcome,
    ConcurrentReplayClaim,
    ReplayTransactionPort,
)
from authorization.domain.idempotency import InvalidReplayInput, ReplayIdentity, ReplayRecord
from common.platform_db import PlatformDatabase


class SqlReplayTransaction[ReceiptT: BaseModel]:
    def __init__(
        self,
        session: AsyncSession,
        identity: ReplayIdentity,
        cipher: Fernet,
        response_model: type[ReceiptT],
        command: Callable[[AsyncSession], Awaitable[CommandOutcome[ReceiptT]]],
        reauthorize: Callable[[AsyncSession], Awaitable[None]],
    ) -> None:
        self.session = session
        self.identity = identity
        self.cipher = cipher
        self.response_model = response_model
        self.command = command
        self.check_authority = reauthorize
        self._claims: dict[UUID, IdempotencyRow] = {}

    async def reauthorize(self) -> None:
        await self.check_authority(self.session)

    async def find(self) -> ReplayRecord | None:
        scope = self.identity
        row = await self.session.scalar(
            select(IdempotencyRow)
            .where(
                IdempotencyRow.actor_scope == scope.actor_scope,
                IdempotencyRow.project_scope == scope.project_scope,
                IdempotencyRow.operation == scope.operation,
                IdempotencyRow.key == scope.key,
            )
            .with_for_update()
        )
        if row is None:
            return None
        return ReplayRecord(
            row.fingerprint, row.status, row.response_status, row.response_ciphertext
        )

    def replay(self, record: ReplayRecord, fingerprint: str) -> CommandOutcome[ReceiptT]:
        record.require_completed(fingerprint)
        ciphertext = record.response_ciphertext
        if ciphertext is None:
            raise RuntimeError("completed replay has no ciphertext")
        decoded = json.loads(self.cipher.decrypt(ciphertext.encode()))
        if not isinstance(decoded, dict):
            raise InvalidReplayInput("stored command response is not an object")
        body = self.response_model.model_validate(decoded)
        return CommandOutcome(record.response_status or 200, body)

    async def claim(self, fingerprint: str) -> UUID:
        scope = self.identity
        row = IdempotencyRow(
            id=uuid4(),
            actor_scope=scope.actor_scope,
            project_scope=scope.project_scope,
            operation=scope.operation,
            key=scope.key,
            fingerprint=fingerprint,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self.session.add(row)
        await self.session.flush()
        self._claims[row.id] = row
        return row.id

    async def perform(self) -> CommandOutcome[ReceiptT]:
        return await self.command(self.session)

    def complete(self, claim_uuid: UUID, outcome: CommandOutcome[ReceiptT]) -> None:
        row = self._claims[claim_uuid]
        row.status = "completed"
        row.response_status = outcome.status
        # Preserve the compact JSON bytes and storage domain-separated cipher.
        encoded = json.dumps(
            outcome.body.model_dump(mode="json"),
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        row.response_ciphertext = self.cipher.encrypt(encoded).decode()


class SqlReplayTransactions[ReceiptT: BaseModel]:
    def __init__(
        self,
        database: PlatformDatabase,
        identity: ReplayIdentity,
        cipher: Fernet,
        response_model: type[ReceiptT],
        command: Callable[[AsyncSession], Awaitable[CommandOutcome[ReceiptT]]],
        reauthorize: Callable[[AsyncSession], Awaitable[None]],
    ) -> None:
        self.database = database
        self.identity = identity
        self.cipher = cipher
        self.response_model = response_model
        self.command = command
        self.reauthorize = reauthorize

    @asynccontextmanager
    async def open(self) -> AsyncIterator[ReplayTransactionPort[ReceiptT]]:
        try:
            async with self.database.transaction() as session:
                yield SqlReplayTransaction(
                    session,
                    self.identity,
                    self.cipher,
                    self.response_model,
                    self.command,
                    self.reauthorize,
                )
        except IntegrityError as exc:
            raise ConcurrentReplayClaim from exc
