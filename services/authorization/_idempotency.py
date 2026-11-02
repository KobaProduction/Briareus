"""Atomic command deduplication with encrypted replayable HTTP outcome.

One transaction includes the deduplication claim, business write, audit/outbox
and encrypted result. PostgreSQL's unique constraint serializes concurrent
claims. No Valkey-only idempotency or duplicate side effect after retry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from authorization.application.idempotency import CommandOutcome as CommandOutcome
from authorization.application.idempotency import (
    ConcurrentReplayClaim,
    ExecuteIdempotentCommand,
    ReceiptT,
)
from authorization.domain.idempotency import (
    InvalidReplayInput,
    ReplayFingerprintConflict,
    ReplayIdentity,
    ReplayPending,
)
from authorization.infrastructure.idempotency import SqlReplayTransactions
from authorization.infrastructure.idempotency_fingerprint import (
    canonical_fingerprint as canonical_fingerprint,
)
from common.platform_db import PlatformDatabase
from common.platform_errors import IdempotencyConflict, InvalidInput, OperationInProgress

from ._crypto_keys import fingerprint_key, replay_fernet_key


class IdempotentCommandExecutor:
    def __init__(self, database: PlatformDatabase, encryption_key: str) -> None:
        self.database = database
        self._cipher = Fernet(replay_fernet_key(encryption_key).encode())
        self._fingerprint_secret = fingerprint_key(encryption_key)

    async def execute(
        self,
        *,
        actor_scope: str,
        project_scope: str,
        operation: str,
        key: str,
        request: BaseModel,
        fingerprint_mode: Literal["python", "json"] = "python",
        command: Callable[[AsyncSession], Awaitable[CommandOutcome[ReceiptT]]],
        reauthorize: Callable[[AsyncSession], Awaitable[None]],
        response_model: type[ReceiptT],
    ) -> CommandOutcome[ReceiptT]:
        identity = ReplayIdentity(actor_scope, project_scope, operation, key)
        try:
            identity.require_valid()
            fingerprint = canonical_fingerprint(
                request, secret=self._fingerprint_secret, mode=fingerprint_mode
            )
            return await ExecuteIdempotentCommand(
                SqlReplayTransactions(
                    self.database,
                    identity,
                    self._cipher,
                    response_model,
                    command,
                    reauthorize,
                )
            ).execute(fingerprint)
        except InvalidReplayInput as exc:
            raise InvalidInput(str(exc)) from exc
        except ReplayFingerprintConflict as exc:
            raise IdempotencyConflict(str(exc)) from exc
        except ReplayPending as exc:
            raise OperationInProgress(str(exc)) from exc
        except ConcurrentReplayClaim as exc:
            # No winning durable claim: preserve the original integrity failure.
            if exc.__cause__ is not None:
                raise exc.__cause__ from None
            raise
