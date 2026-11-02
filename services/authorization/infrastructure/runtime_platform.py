"""Lifecycle and concrete capability assembly for the private owner HTTP listener."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request
from pydantic import SecretStr

from authorization._approval_read_api import ApprovalListReader, TrustedApprovalListAttestor
from authorization._decision_api import (
    AuthorizationDecisionReader,
    AuthorizationDecisionService,
    TrustedDecisionAttestor,
)
from authorization._files_read_decision import FilesReadDecisionService
from authorization._idempotency import IdempotentCommandExecutor
from authorization._rauthy_access_commands import (
    AccessRauthyCommandService,
    TrustedAccessCommandAttestor,
)
from authorization._resource_scope import TrustedResourceOwnerPort
from common.owner_migrations import verify_owner
from common.owner_runtime import OwnerIngressVerifier
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase


@dataclass(frozen=True, slots=True)
class AccessRuntimeAuthorities:
    ingress: OwnerIngressVerifier | None
    decisions: TrustedDecisionAttestor | None
    approvals: TrustedApprovalListAttestor | None
    commands: TrustedAccessCommandAttestor | None
    command_key: SecretStr | None
    resource_owners: TrustedResourceOwnerPort | None

    @property
    def configured(self) -> bool:
        has_reader = self.decisions is not None or self.approvals is not None
        has_writer = self.commands is not None and self.command_key is not None
        return self.ingress is not None and (has_reader or has_writer)


class AccessPlatformRuntime:
    def __init__(self, authorities: AccessRuntimeAuthorities) -> None:
        self.authorities = authorities
        self.database: PlatformDatabase | None = None
        self.idempotency: IdempotentCommandExecutor | None = None

    @asynccontextmanager
    async def lifespan(
        self,
        app: FastAPI,
        owner_lifespan: Callable[[FastAPI], AbstractAsyncContextManager[object]],
    ) -> AsyncIterator[None]:
        async with owner_lifespan(app):
            if not self.authorities.configured:
                yield
                return
            settings = OwnerDatabaseSettings(owner="access")
            database = PlatformDatabase(settings)
            try:
                await verify_owner(database, settings)
                self.database = database
                key = self.authorities.command_key
                if self.authorities.commands is not None and key is not None:
                    self.idempotency = IdempotentCommandExecutor(database, key.get_secret_value())
                yield
            finally:
                self.idempotency = None
                self.database = None
                await database.close()

    def decisions(self, _request: Request) -> AuthorizationDecisionService | None:
        attestor = self.authorities.decisions
        database = self.database
        if self.authorities.ingress is None or attestor is None or database is None:
            return None
        return AuthorizationDecisionService(attestor, AuthorizationDecisionReader(database))

    def approvals(self) -> ApprovalListReader | None:
        attestor = self.authorities.approvals
        database = self.database
        if self.authorities.ingress is None or attestor is None or database is None:
            return None
        return ApprovalListReader(database=database, attestor=attestor)

    def commands(self) -> AccessRauthyCommandService | None:
        attestor = self.authorities.commands
        database, idempotency = self.database, self.idempotency
        if (
            self.authorities.ingress is None
            or attestor is None
            or database is None
            or idempotency is None
        ):
            return None
        return AccessRauthyCommandService(
            database=database,
            idempotency=idempotency,
            attestor=attestor,
            resource_owner=self.authorities.resource_owners,
        )

    def files(self) -> FilesReadDecisionService | None:
        attestor = self.authorities.decisions
        database, owners = self.database, self.authorities.resource_owners
        if (
            self.authorities.ingress is None
            or attestor is None
            or database is None
            or owners is None
        ):
            return None
        return FilesReadDecisionService(
            attestor=attestor,
            reader=AuthorizationDecisionReader(database),
            resource_owner=owners,
        )
