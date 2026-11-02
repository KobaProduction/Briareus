"""Legacy resource receipt transaction adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._idempotency import CommandOutcome, IdempotentCommandExecutor
from authorization._project_access import CallerPrincipal
from common.platform_errors import InvalidInput
from infrastructure.resource_replay_authority import ResourceReplayAuthority
from projects._resource_service import ResourceService

ReceiptT = TypeVar("ReceiptT", bound=BaseModel)


@dataclass(frozen=True)
class ResourceCommandRunner:
    resources: ResourceService
    commands: IdempotentCommandExecutor

    async def __call__(
        self,
        caller: CallerPrincipal,
        payload: BaseModel,
        *,
        key: str | None,
        owner_scope: str,
        operation: str,
        execute: Callable[[AsyncSession], Awaitable[CommandOutcome[ReceiptT]]],
        response_model: type[ReceiptT],
    ) -> ReceiptT:
        if key is None:
            raise InvalidInput("Idempotency-Key required for resource mutation")

        authority = ResourceReplayAuthority(self.resources, caller, owner_scope, operation)

        outcome = await self.commands.execute(
            actor_scope=str(caller.user_id),
            project_scope=owner_scope,
            operation=operation,
            key=key,
            request=payload,
            command=execute,
            reauthorize=authority.reauthorize,
            response_model=response_model,
        )
        return outcome.body
