"""Legacy command receipt transaction adapter with locked replay authority."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from application.platform_contracts import ApiModel, CreateProject
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._idempotency import CommandOutcome, IdempotentCommandExecutor
from authorization._platform_application import PlatformApplication
from authorization._project_access import CallerPrincipal
from common.platform_errors import InvalidInput
from identity._service import IdentityService
from infrastructure.platform_replay_authority import PlatformReplayAuthority

ReceiptT = TypeVar("ReceiptT", bound=BaseModel)


@dataclass(frozen=True)
class PlatformCommandRunner:
    application: PlatformApplication
    identity: IdentityService
    commands: IdempotentCommandExecutor

    async def __call__(
        self,
        *,
        key: str | None,
        actor_scope: str,
        project_scope: str,
        operation: str,
        payload: ApiModel,
        callback: Callable[[AsyncSession], Awaitable[CommandOutcome[ReceiptT]]],
        response_model: type[ReceiptT],
        caller_identity: CallerPrincipal | None = None,
    ) -> ReceiptT:
        if key is None:
            raise InvalidInput("Idempotency-Key is required for mutations")

        if operation == "project.create" and not isinstance(payload, CreateProject):
            raise InvalidInput("invalid Project creation contract")
        authority = PlatformReplayAuthority(
            self.application,
            self.identity,
            caller_identity,
            operation,
            project_scope,
            payload.owner_team_id if isinstance(payload, CreateProject) else None,
        )

        result = await self.commands.execute(
            actor_scope=actor_scope,
            project_scope=project_scope,
            operation=operation,
            key=key,
            request=payload,
            command=callback,
            reauthorize=authority.reauthorize,
            response_model=response_model,
        )
        return result.body
