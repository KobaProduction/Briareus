"""Fail-closed private owner HTTP composition over independent authority ports."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import SecretStr

from authorization._approval_read_api import (
    TrustedApprovalListAttestor,
    private_approval_list_router,
)
from authorization._decision_api import (
    AuthorizationDecisionService,
    TrustedDecisionAttestor,
    authorization_decision_router,
)
from authorization._files_read_decision import files_read_decision_router
from authorization._rauthy_access_command_api import rauthy_access_command_router
from authorization._rauthy_access_commands import TrustedAccessCommandAttestor
from authorization._resource_scope import TrustedResourceOwnerPort
from authorization.infrastructure.runtime_platform import (
    AccessPlatformRuntime,
    AccessRuntimeAuthorities,
)
from common.owner_runtime import OwnerIngressVerifier, create_owner_app


def create_authorization_app(
    decision_service: AuthorizationDecisionService | None = None,
    *,
    trusted_attestor: TrustedDecisionAttestor | None = None,
    trusted_approvals: TrustedApprovalListAttestor | None = None,
    trusted_commands: TrustedAccessCommandAttestor | None = None,
    command_encryption_key: SecretStr | None = None,
    current_resource_owners: TrustedResourceOwnerPort | None = None,
    trusted_ingress: OwnerIngressVerifier | None = None,
) -> FastAPI:
    app = create_owner_app("access", trusted_ingress=trusted_ingress)
    runtime = AccessPlatformRuntime(
        AccessRuntimeAuthorities(
            trusted_ingress,
            trusted_attestor,
            trusted_approvals,
            trusted_commands,
            command_encryption_key,
            current_resource_owners,
        )
    )
    owner_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(current_app: FastAPI) -> AsyncIterator[None]:
        async with runtime.lifespan(current_app, owner_lifespan):
            yield

    app.router.lifespan_context = lifespan
    app.include_router(
        authorization_decision_router(decision_service, resolve_service=runtime.decisions)
    )
    app.include_router(private_approval_list_router(resolve_reader=runtime.approvals))
    app.include_router(rauthy_access_command_router(resolve_service=runtime.commands))
    app.include_router(files_read_decision_router(resolve_service=runtime.files))
    return app


app = create_authorization_app()
