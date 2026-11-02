"""Human module invocation through real resource credentials and current MCP admission."""

from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from control_panel_api.application._constructor_bindings import _SessionsBinding
from control_panel_api.application.module_commands import HumanToolCommand
from control_panel_api.domain.module_preparation import ModuleTarget
from control_panel_api.domain.oidc_identity import PrivateOidcResourceCredential
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_management import RpcFailure

from .module_contracts import (
    ModuleRequest,
    ModuleScope,
)
from .module_preparation import McpSession, PreparedExchange


class HumanModuleAuthority(Protocol):
    async def current(self, project: UUID) -> PanelContext | None: ...


class ModuleResourceOwner(Protocol):
    async def scope(
        self, context: PanelContext, project: UUID, target: ModuleTarget
    ) -> ModuleScope: ...


class ModuleCredentials(Protocol):
    async def resolve(self, module: str) -> PrivateOidcResourceCredential | None: ...


class McpSessions[Reply](Protocol):
    def open(
        self,
        target: ModuleTarget,
        context: PanelContext,
        command: HumanToolCommand,
        credential: PrivateOidcResourceCredential,
    ) -> AbstractAsyncContextManager[McpSession[Reply]]: ...


class McpInvocation[Reply](_SessionsBinding[McpSessions[Reply]]):
    async def invoke(
        self,
        target: ModuleTarget,
        context: PanelContext,
        command: HumanToolCommand,
        credential: PrivateOidcResourceCredential,
    ) -> Reply:
        async with self._sessions.open(target, context, command, credential) as session:
            preparation = PreparedExchange(session, target)
            await preparation.initialize()
            await session.initialized()
            return await preparation.run(command)


class HumanModule[Reply]:
    def __init__(
        self,
        authority: HumanModuleAuthority,
        resources: ModuleResourceOwner | None,
        credentials: ModuleCredentials,
        invocation: McpInvocation[Reply],
    ) -> None:
        self._authority = authority
        self._resources = resources
        self._credentials = credentials
        self._invocation = invocation

    async def _command(
        self,
        target: ModuleTarget,
        context: PanelContext,
        command: HumanToolCommand,
    ) -> Reply:
        credential = await self._credentials.resolve(target.module)
        if (
            credential is None
            or credential.issuer != context.session.issuer
            or credential.subject != context.session.subject
            or credential.expires_at <= datetime.now(UTC)
        ):
            raise RpcFailure(target.prefix.upper() + "_CREDENTIAL_UNAVAILABLE")
        return await self._invocation.invoke(target, context, command, credential)

    async def execute(self, target: ModuleTarget, request: ModuleRequest) -> ModuleScope | Reply:
        context = await self._authority.current(request.project_uuid)
        if context is None:
            raise RpcFailure("CURRENT_PLATFORM_REQUIRED")
        if request.command is None:
            if self._resources is None:
                raise RpcFailure(target.prefix.upper() + "_OWNER_UNAVAILABLE")
            result: ModuleScope | Reply = await self._resources.scope(
                context, request.project_uuid, target
            )
        else:
            result = await self._command(target, context, request.command)
        fresh = await self._authority.current(request.project_uuid)
        if (
            fresh is None
            or fresh.proof.user_uuid != context.proof.user_uuid
            or fresh.session.subject != context.session.subject
            or fresh.proof.issuer != context.proof.issuer
            or min(fresh.session.expires_at, fresh.proof.expires_at) <= datetime.now(UTC)
        ):
            raise RpcFailure(target.prefix.upper() + "_CURRENT_AUTHORITY_REQUIRED")
        return result
